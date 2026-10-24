"""Strategy composition and durable lifecycle used by the shared trainer loop."""
from __future__ import annotations

import math
import time
from dataclasses import asdict
from pathlib import Path

from skillopt.datasets.base import BatchSpec
from skillopt.evaluation.gate import GateResult
from skillopt.optimizer.skill import apply_patch_with_report

from .budget import select
from .config import ReMemConfig
from .context import FailureMemory, NoMemory
from .evaluation import PairedBootstrapGate, aligned_scores
from .evidence import rule_index, validate_edit, validate_proposal
from .proposals import JsonProposalStrategy
from .store import EventStore
from .types import FailureEvent, RepairAttempt, canonical, digest


class InfrastructureFailure(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


def classify(row: dict) -> tuple[str, str]:
    reason = str(row.get("fail_reason", ""))
    infra_prefixes = ("llm-call-failed", "no-test-cases", "unsafe-task-id", "timeout", "task-timeout", "load error", "missing-file", "unexpected:", "worker-error")
    case_errors = [str(c.get("error", "")) + str(c.get("reason", "")) for c in row.get("cases", []) if isinstance(c, dict)]
    if (row.get("outcome") == "infra_failure" or row.get("llm_ok") is False or reason.startswith(infra_prefixes)
            or any("timeout after" in e or "eval-exception:" in e or "load error:" in e for e in case_errors)):
        return "infra_failure", reason.split(":", 1)[0] or "infrastructure"
    score = row.get("hard")
    if not isinstance(score, (int, float)) or not math.isfinite(score) or score not in (0, 1):
        return "infra_failure", "invalid_result_contract"
    if score == 1:
        return "success", "none"
    # This signature is an observed outcome category, not a causal diagnosis.
    return "failure", str(row.get("failure_kind") or reason.split(":", 1)[0] or "task_failure")[:120]


class ReMemRuntime:
    def __init__(self, cfg: dict, dataloader, chat):
        self.options = ReMemConfig.parse(cfg)
        if self.options is None:
            raise ValueError("ReMem is not enabled")
        self.cfg, self.chat = cfg, chat
        self.root = Path(cfg["out_root"]).resolve()
        if dataloader is None or not hasattr(dataloader, "train_items"):
            raise ValueError("ReMem needs an explicit dataset train/selection registry")
        self.train_items = {str(r["id"]): r for r in dataloader.train_items}
        self.selection_ids = {str(r["id"]) for r in dataloader.val_items}
        if len(self.train_items) != len(dataloader.train_items) or len(self.selection_ids) != len(dataloader.val_items):
            raise ValueError("Duplicate registry IDs")
        if not self.train_items or not self.selection_ids or set(self.train_items) & self.selection_ids:
            raise ValueError("Empty or overlapping train/selection registries")
        self.schedule = self.options.task_schedule
        for batch in self.schedule:
            if not isinstance(batch, list) or not batch or len(batch) != len(set(batch)) or not set(batch) <= set(self.train_items):
                raise ValueError("Invalid fixed task schedule")
            if len(batch) != cfg["batch_size"]:
                raise ValueError("Scheduled batch size differs from trainer configuration")
        # Freeze the full effective configuration hash, not only visible model aliases.
        # No plaintext config/credentials are written to the ledger.
        identity = {"options": self.options.identity(), "config_hash": digest(canonical(cfg)),
                    "train_registry_hash": digest(canonical(dataloader.train_items)),
                    "selection_ids": sorted(self.selection_ids)}
        self.store = EventStore(self.root / "remem", identity)
        self.memory = FailureMemory(self.store, self.options.top_k, self.options.max_attempts,
                                    self.options.memory_character_cap) if self.options.memory else NoMemory()
        self.proposals = JsonProposalStrategy(self.options.repair, self._call, self.options.max_proposals)
        self.gate = PairedBootstrapGate(self.options.bootstrap_samples, self.options.confidence, int(cfg["seed"]))
        self.step = 0
        self.before = ""
        self.current: list[dict] = []
        self.selected: list[dict] = []
        self.proposal_status = "no_proposal"

    def begin_step(self, step: int, skill: str) -> None:
        self.step, self.before = step, skill
        self.current, self.selected = [], []
        self.proposal_status = "no_proposal"

    def batches(self, seed: int) -> list[BatchSpec]:
        return [BatchSpec("train", "train", seed + i, len(ids), [self.train_items[t] for t in ids])
                for i, ids in enumerate(self.schedule)]

    def _call(self, system: str, user: str) -> str:
        requests = self.store.records("optimizer_started")
        if len(requests) >= self.options.optimizer_calls:
            self.store.append(f"budget_exhausted:optimizer:{self.step}", "budget_exhausted", {"step": self.step, "resource": "optimizer_calls"})
            raise BudgetExhausted("Optimizer logical-call budget exhausted")
        call_id = f"optimizer:{len(requests)+1}"
        self.store.append(call_id, "optimizer_started", {"step": self.step, "request_hash": digest(system + user)})
        started = time.monotonic()
        try:
            text, usage = self.chat(system=system, user=user, max_completion_tokens=self.options.optimizer_output_tokens,
                                    retries=1, stage="remem_proposal")
        except Exception as exc:
            self.store.append(call_id + ":error", "optimizer_error", {"step": self.step, "error_type": type(exc).__name__,
                              "elapsed_s": time.monotonic()-started, "usage": None, "http_attempts": None})
            raise InfrastructureFailure("Optimizer service call failed; see typed ledger record") from exc
        self.store.append(call_id + ":done", "optimizer_completed", {"step": self.step, "elapsed_s": time.monotonic()-started,
                          "usage": usage if isinstance(usage, dict) and usage else None,
                          "http_attempts": None, "response_hash": digest(str(text))})
        if not isinstance(text, str) or not text.strip():
            self.store.append(call_id + ":empty", "optimizer_error", {"step": self.step, "error_type": "empty_content"})
            raise InfrastructureFailure("Optimizer returned empty content")
        return text

    def _snapshot(self, row: dict, rollout_dir: Path) -> dict:
        task = str(row["id"])
        if task not in self.train_items:
            raise ValueError("Training result outside registry")
        outcome, kind = classify(row)
        if outcome == "infra_failure":
            self.store.append(f"infra:{self.step}:{task}", "infra_failure", {"step": self.step, "task_id": task, "kind": kind})
            return {}
        trace_fields = {k: row[k] for k in ("task_description", "fail_reason", "code", "trajectory", "predicted_answer", "spreadsheet_preview") if k in row}
        trace_fields["instruction"] = self.train_items[task].get("instruction", "")
        trace_root = (rollout_dir / "predictions" / task).resolve()
        if not trace_root.is_relative_to(rollout_dir.resolve()):
            raise ValueError("Trace path escapes rollout")
        for filename in ("code.py", "conversation.json"):
            path = trace_root / filename
            if path.is_file():
                if not path.resolve().is_relative_to(rollout_dir.resolve()):
                    raise ValueError("Trace symlink escapes rollout")
                trace_fields[filename] = path.read_text(encoding="utf-8")
        trace = canonical(trace_fields)
        clipped = len(trace) > self.options.trace_character_cap
        trace = trace[:self.options.trace_character_cap]
        artifact_hash = self.store.artifact({"trace": trace, "truncated": clipped, "full_trace_hash": digest(canonical(trace_fields))})
        event_id = digest(canonical([self.options.run_id, self.step, task, digest(self.before)]))
        event = FailureEvent(event_id, self.options.run_id, task, digest(self.before), self.step, outcome, kind, artifact_hash)
        self.store.observe(event)
        return {**asdict(event), "case_id": digest(canonical([task, kind])) if outcome == "failure" else None,
                "trace": trace, "trace_truncated": clipped}

    def rollout(self, adapter, env, skill: str, out_dir: str, *, phase: str, **kwargs) -> list[dict]:
        if phase not in {"train", "selection"}:
            raise ValueError("Test execution is forbidden during optimization")
        ids = [str(r["id"]) for r in env]
        registry = set(self.train_items) if phase == "train" else self.selection_ids
        if len(ids) != len(set(ids)) or not ids or not set(ids) <= registry:
            raise ValueError("Rollout task identity mismatch")
        if phase == "selection" and set(ids) != self.selection_ids:
            raise ValueError("Selection must cover the entire frozen selection registry")
        key = digest(canonical([phase, digest(skill), ids, self.step if phase == "train" else "selection_draw_0"]))
        cached = self.store.get("rollout_done:" + key)
        if cached:
            rows = self.store.read_artifact(cached["artifact_hash"])["rows"]
            self.store.append(f"cache:{self.step}:{key}", "cache_hit", {"step": self.step, "phase": phase, "key": key})
        else:
            if self.store.get("rollout_start:" + key):
                raise InfrastructureFailure("Interrupted rollout needs explicit reconciliation; no silent free retry")
            spent = sum(r["tasks"] for r in self.store.records("rollout_started"))
            if spent + len(ids) > self.options.task_executions:
                self.store.append(f"budget_exhausted:tasks:{self.step}", "budget_exhausted", {"step": self.step, "resource": "task_executions"})
                raise BudgetExhausted("Task execution budget exhausted")
            self.store.append("rollout_start:" + key, "rollout_started", {"phase": phase, "step": self.step, "tasks": len(ids)})
            started = time.monotonic()
            try:
                rows = adapter.rollout(env, skill, out_dir, **kwargs)
            except Exception as exc:
                self.store.append("rollout_error:" + key, "infra_failure", {"phase": phase, "step": self.step, "error_type": type(exc).__name__})
                raise
            artifact_hash = self.store.artifact({"rows": rows})
            self.store.append("rollout_done:" + key, "rollout_completed", {"phase": phase, "step": self.step,
                              "artifact_hash": artifact_hash, "elapsed_s": time.monotonic()-started,
                              "http_attempts": None, "usage": None})
        returned = [str(r.get("id")) for r in rows]
        if phase == "train":
            # Persist EVERY valid observation before considering any other result's error.
            self.current = [observation for row in rows if str(row.get("id")) in registry
                            and returned.count(str(row.get("id"))) == 1
                            and (observation := self._snapshot(row, Path(out_dir)))]
        if len(returned) != len(ids) or set(returned) != set(ids):
            raise InfrastructureFailure("Missing, duplicate or foreign rollout results; valid failures preserved")
        bad = [r for r in rows if classify(r)[0] == "infra_failure"]
        if bad:
            raise InfrastructureFailure("Infrastructure failure in rollout; valid training failures were preserved")
        if phase == "selection":
            aligned_scores(rows)
            selection = [{k: r[k] for k in ("id", "hard", "soft") if k in r} for r in rows]
            self.store.append("selection:" + digest(skill), "selection", {"artifact_hash": self.store.artifact({"rows": selection})})
        return rows

    def reflect(self, results, skill: str, out_dir: str, **kwargs) -> list[dict]:
        memory = self.memory.retrieve(task_ids={r["task_id"] for r in self.current}, skill_hash=digest(skill), before_step=self.step)
        allowed = {r["event_id"] for r in self.current} | {g["observation"]["event_id"] for g in memory}
        artifact = self.store.artifact({"current": self.current, "history": memory,
                                       "skill_hash": digest(skill), "rule_sidecar": rule_index(skill)})
        self.store.append(f"context:{self.step}", "context", {"step": self.step, "artifact_hash": artifact,
                          "history_groups": len(memory), "history_characters": len(canonical(memory)),
                          "history_token_estimate": (len(canonical(memory))+3)//4})
        saved = self.store.get(f"proposal_result:{self.step}")
        if saved is None:
            proposal_result = self.proposals.propose(skill, self.current, memory)
            saved = asdict(proposal_result)
            self.store.append(f"proposal_result:{self.step}", "proposal_result", saved)
        self.proposal_status = saved["status"]
        valid = []
        proposal_ids = set()
        for i, proposal in enumerate(saved["proposals"]):
            try:
                if self.options.repair:
                    validate_proposal(proposal, skill, allowed, self.store)
                    if proposal["proposal_id"] in proposal_ids:
                        raise ValueError("Duplicate proposal ID")
                    proposal_ids.add(proposal["proposal_id"])
                else:
                    validate_edit(proposal, skill)
                valid.append(proposal)
            except (ValueError, TypeError, KeyError) as exc:
                self.store.append(f"invalid:{self.step}:{i}", "proposal_invalid", {"step": self.step, "index": i, "reason": str(exc)})
        if saved["proposals"] and not valid:
            self.proposal_status = "proposal_invalid"
        if self.options.repair:
            valid.sort(key=lambda p: -len({self.store.get(ref["event_id"])["task_id"] for ref in p["evidence_refs"]}))
        self.selected, audit = select(valid, self.options.max_edits, repair=self.options.repair)
        self.store.append(f"budget:{self.step}", "proposal_budget", {"step": self.step, "decisions": audit})
        edits = [p["patch"] if self.options.repair else p for p in self.selected]
        if not edits:
            self.finish(self.proposal_status, skill)
            return []
        return [{"patch": {"edits": edits}, "source_type": "failure"}]

    def aggregate(self, skill, failure, success, **kwargs):
        return {"edits": [e for p in failure + success for e in p.get("edits", p.get("patch", {}).get("edits", []))]}

    def rank(self, skill, merged, **kwargs):
        return merged

    def apply(self, skill, patch):
        candidate, report = skill, []
        for edit in patch["edits"]:
            validate_edit(edit, candidate)
            candidate, current_report = apply_patch_with_report(candidate, {"edits": [edit]})
            report.extend(current_report)
        if any(not r["status"].startswith("applied") for r in report):
            raise ValueError("Validated edit bundle could not be applied atomically")
        return candidate, report

    def evaluate_gate(self, **kwargs):
        before = self.store.get("selection:" + digest(kwargs["current_skill"]))
        after = self.store.get("selection:" + digest(kwargs["candidate_skill"]))
        if before is None or after is None:
            raise ValueError("Paired gate requires recorded per-task evidence for both versions")
        result = self.gate.compare(self.store.read_artifact(before["artifact_hash"])["rows"], self.store.read_artifact(after["artifact_hash"])["rows"])
        self.store.append(f"gate:{self.step}", "gate", {"step": self.step, **result})
        accepted = result["action"] == "accept"
        self.finish(result["action"], kwargs["candidate_skill"], accepted)
        if accepted:
            return GateResult("accept_new_best", kwargs["candidate_skill"], kwargs["cand_hard"],
                              kwargs["candidate_skill"], kwargs["cand_hard"], kwargs["global_step"])
        return GateResult(result["action"], kwargs["current_skill"], kwargs["current_score"],
                          kwargs["best_skill"], kwargs["best_score"], kwargs["best_step"])

    def finish(self, action: str, candidate: str, adopted: bool = False) -> None:
        case_ids = {r["case_id"] for r in self.current if r["case_id"]}
        if self.options.repair:
            case_ids.update(c for p in self.selected for c in p["failure_case_ids"])
        cases = tuple(sorted(case_ids))
        proposals = tuple(p["proposal_id"] if self.options.repair else f"free_{i}" for i, p in enumerate(self.selected))
        edits = tuple(p["patch"] if self.options.repair else p for p in self.selected)
        attempt = RepairAttempt(f"attempt:{self.step}", self.step, digest(self.before), digest(candidate), cases, proposals, action, adopted, edits)
        self.store.append(attempt.attempt_id, "attempt", asdict(attempt))

    def summary(self) -> dict:
        return {"observations": len(self.store.records("observation")), "attempts": len(self.store.records("attempt")),
                "task_executions": sum(r["tasks"] for r in self.store.records("rollout_started")),
                "optimizer_logical_calls": len(self.store.records("optimizer_started")),
                "cache_hits": len(self.store.records("cache_hit")), "http_attempts": None,
                "usage_coverage": "partial_or_missing", "formal_ready": False}

    def checkpoint(self, state: dict, history: list[dict], current_skill: str, best_skill: str) -> None:
        artifact = self.store.artifact({"state": state, "history": history,
                                       "current_skill": current_skill, "best_skill": best_skill})
        self.store.append(f"checkpoint:{state['last_completed_step']}", "checkpoint", {"artifact_hash": artifact})

    def restore(self) -> dict | None:
        checkpoints = self.store.records("checkpoint")
        return self.store.read_artifact(checkpoints[-1]["artifact_hash"]) if checkpoints else None
