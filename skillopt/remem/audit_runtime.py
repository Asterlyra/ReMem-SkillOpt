"""Shared execution audit and checkpoints; never supplies optimizer context."""
from __future__ import annotations

import math
import time
from dataclasses import asdict
from pathlib import Path

from skillopt.datasets.base import BatchSpec

from .evaluation import aligned_scores
from .types import FailureEvent, canonical, digest


class InfrastructureFailure(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


def classify(row: dict) -> tuple[str, str]:
    reason = str(row.get("fail_reason", ""))
    infra_prefixes = ("llm-call-failed", "no-test-cases", "unsafe-task-id", "timeout", "task-timeout", "load error", "missing-file", "unexpected:", "worker-error")
    cases = [c for c in row.get("cases", []) if isinstance(c, dict)]
    # The executor has already run model-generated code under a fixed limit.
    # Its bounded execution failure is a task outcome, distinct from a worker,
    # service, evaluator, or whole-task timeout. Require the structured stage.
    code_timeout = (row.get("llm_ok") is True and reason.startswith("exec-error: timeout after ")
                    and any(c.get("stage") == "exec" and c.get("ok") is False
                            and str(c.get("error", "")).startswith("timeout after ") for c in cases))
    case_errors = [(c, str(c.get("error", "")) + str(c.get("reason", ""))) for c in cases]
    if (row.get("outcome") == "infra_failure" or row.get("llm_ok") is False or reason.startswith(infra_prefixes)
            or any(("timeout after" in e and not (code_timeout and c.get("stage") == "exec"))
                   or "eval-exception:" in e or "load error:" in e for c, e in case_errors)):
        return "infra_failure", reason.split(":", 1)[0] or "infrastructure"
    score = row.get("hard")
    if not isinstance(score, (int, float)) or not math.isfinite(score) or score not in (0, 1):
        return "infra_failure", "invalid_result_contract"
    if code_timeout:
        return ("failure", "generated_code_timeout") if score == 0 else ("infra_failure", "invalid_result_contract")
    if score == 1:
        return "success", "none"
    # This signature is an observed outcome category, not a causal diagnosis.
    return "failure", str(row.get("failure_kind") or reason.split(":", 1)[0] or "task_failure")[:120]


class RuntimeAudit:
    """Only task execution, training observations and resume infrastructure."""

    def batches(self, seed: int) -> list[BatchSpec]:
        return [BatchSpec("train", "train", seed + i, len(ids), [self.train_items[t] for t in ids])
                for i, ids in enumerate(self.schedule)]


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
            self.store.append("rollout_invalid:" + key, "infra_failure", {"step": self.step,
                "phase": phase, "task_ids": [str(r["id"]) for r in bad], "kind": "invalid_task_execution"})
            raise InfrastructureFailure("Infrastructure failure in rollout; valid training failures were preserved")
        if phase == "selection":
            aligned_scores(rows)
            selection = [{k: r[k] for k in ("id", "hard", "soft", "task_type") if k in r} for r in rows]
            self.store.append("selection:" + digest(skill), "selection", {"artifact_hash": self.store.artifact({"rows": selection})})
        return rows


    def checkpoint(self, state: dict, history: list[dict], current_skill: str, best_skill: str) -> None:
        artifact = self.store.artifact({"state": state, "history": history,
                                       "current_skill": current_skill, "best_skill": best_skill})
        self.store.append(f"checkpoint:{state['last_completed_step']}", "checkpoint", {"artifact_hash": artifact})


    def restore(self) -> dict | None:
        checkpoints = self.store.records("checkpoint")
        return self.store.read_artifact(checkpoints[-1]["artifact_hash"]) if checkpoints else None

