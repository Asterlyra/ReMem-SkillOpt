"""Native SkillOpt strategies and a provenance-pinned CAM v3 mechanism port."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from skillopt.evaluation.gate import GateResult, evaluate_gate
from skillopt.gradient.aggregate import merge_patches
from skillopt.optimizer.clip import rank_and_select
from skillopt.optimizer.skill import apply_patch_with_report

from .audit_runtime import InfrastructureFailure, RuntimeAudit
from .call_policy import assert_calls_healthy, record_format_error
from .store import EventStore
from .types import canonical, digest

CAM_V3 = {"cam_soft_accept_policy": "noninferiority", "cam_noninferiority_margin": .05,
          "cam_group_guard": True, "cam_group_max_regression": .10, "cam_group_min_pairs": 5,
          "cam_confidence_level": .95, "cam_meaningful_improvement": 0., "cam_bootstrap_samples": 10000,
          "cam_memory_min_similarity": .15, "cam_memory_half_life_steps": 8,
          "cam_memory_top_k": 3, "cam_budget_min_support_tasks": 2,
          "cam_drift_patience": 2, "cam_drift_tolerance": 0.}


class NativeControlRuntime(RuntimeAudit):
    def __init__(self, cfg, dataloader, adapter):
        if cfg.get("control_kind") not in {"skillopt_controlled", "cam_reference"}:
            raise ValueError("Unsupported native control")
        if any(cfg.get(k, False) for k in ("eval_test", "use_slow_update", "use_meta_skill", "use_skill_aware_reflection")):
            raise ValueError("External control requires isolated fixed-patch optimization")
        self.cfg, self.adapter = cfg, adapter
        self.root = Path(cfg["out_root"])
        self.train_items = {str(row["id"]): row for row in dataloader.train_items}
        self.selection_ids = {str(row["id"]) for row in dataloader.val_items}
        if not self.train_items or not self.selection_ids or set(self.train_items) & self.selection_ids:
            raise ValueError("Empty or overlapping train/selection registry")
        if len(self.train_items) != len(dataloader.train_items) or len(self.selection_ids) != len(dataloader.val_items):
            raise ValueError("Duplicate task IDs")
        self.schedule = cfg["control_task_schedule"]
        if any(not batch or len(batch) != cfg["batch_size"] or len(batch) != len(set(batch))
               or not set(batch) <= set(self.train_items) for batch in self.schedule):
            raise ValueError("Invalid native fixed task schedule")
        limits = cfg.get("research_limits", {})
        self.options = SimpleNamespace(task_executions=limits.get("task_executions", 400),
                                       trace_character_cap=12000, run_id=str(self.root))
        self.store = EventStore(self.root / "remem", {"control": cfg["control_kind"],
                                "config_hash": digest(canonical(cfg)),
                                "train_registry_hash": digest(canonical(dataloader.train_items)),
                                "selection_ids": sorted(self.selection_ids)})
        self.cam = cfg["control_kind"] == "cam_reference"
        self.cam_cfg = {**CAM_V3, **cfg.get("cam_control", {}), "seed": cfg["seed"]}
        self.current, self.selected, self.training_rows = [], [], []
        self.step, self.before = 0, ""
        if self.cam:
            from .vendor.cam.drift_guard import DriftGuard
            from .vendor.cam.rejected_memory import PersistentRejectedEditMemory
            self.memory = PersistentRejectedEditMemory(self.root / "remem/cam_memory.json", policy="evidence_v3",
                min_similarity=self.cam_cfg["cam_memory_min_similarity"], half_life_steps=self.cam_cfg["cam_memory_half_life_steps"])
            previous = self.store.records("cam_gate")
            self.drift = DriftGuard(self.cam_cfg["cam_drift_patience"], self.cam_cfg["cam_drift_tolerance"],
                                    state=previous[-1]["drift"] if previous else None)

    def begin_step(self, step, skill):
        self.step, self.before = step, skill
        self.current, self.selected, self.training_rows = [], [], []

    def _stage(self, name, function, *args, **kwargs):
        assert_calls_healthy()
        identity = f"native:{self.step}:{name}"
        old = self.store.get(identity)
        if old:
            return self.store.read_artifact(old["artifact_hash"])["result"]
        if self.store.get(identity + ":start"):
            raise InfrastructureFailure("Interrupted native optimizer stage requires reconciliation")
        self.store.append(identity + ":start", "native_stage_started", {"step": self.step, "stage": name})
        result = function(*args, **kwargs)
        assert_calls_healthy()
        try:
            patches = [row["patch"] for row in result] if name == "reflect" else [result]
            if name == "reflect" and not isinstance(result, list):
                raise ValueError("reflection must return a list")
            for patch in patches:
                if not isinstance(patch, dict) or not isinstance(patch.get("edits"), list):
                    raise ValueError("missing edit list")
                for edit in patch["edits"]:
                    if not isinstance(edit, dict) or edit.get("op") not in {"append", "insert_after", "replace", "delete"}:
                        raise ValueError("unknown edit")
                    if any(not isinstance(edit.get(k, ""), str) for k in ("target", "content")):
                        raise ValueError("invalid edit field")
                    if edit["op"] != "delete" and not edit.get("content", "").strip():
                        raise ValueError("empty edit content")
        except (ValueError, TypeError, KeyError):
            self.store.append(identity + ":invalid", "proposal_invalid", {"step": self.step, "stage": name})
            record_format_error("native_" + name)
            raise InfrastructureFailure("Malformed native optimizer result; see proposal_invalid record") from None
        self.store.append(identity, "native_stage_completed", {"step": self.step, "stage": name,
                          "artifact_hash": self.store.artifact({"result": result})})
        return result

    def reflect(self, results, skill, out_dir, **kwargs):
        self.training_rows = results
        if self.cam:
            from .vendor.cam.memory_context import prepare_memory_context
            context, audit = prepare_memory_context(self.memory, results, benchmark="spreadsheetbench", epoch=1,
                                                    step=self.step, top_k=self.cam_cfg["cam_memory_top_k"])
            kwargs["step_buffer_context"] = kwargs.get("step_buffer_context", "") + "\n" + context
            self.store.append(f"cam_context:{self.step}", "cam_context", {**audit,
                              "artifact_hash": self.store.artifact({"context": context})})
        patches = self._stage("reflect", self.adapter.reflect, results, skill, out_dir, **kwargs)
        if not any(p and p.get("patch", {}).get("edits") for p in patches):
            self.store.append(f"native_no_change:{self.step}", "native_no_change", {"step": self.step})
        return patches

    def aggregate(self, skill, failure, success, **kwargs):
        return self._stage("merge", merge_patches, skill, failure, success, **kwargs)

    def rank(self, skill, patch, **kwargs):
        if self.cam:
            from .vendor.cam.adaptive_budget import compute_evidence_budget
            training_ids = {str(row["id"]) for row in self.training_rows}
            edits, discarded = [], set()
            for item in patch.get("edits", []):
                edit = dict(item)
                for field in ("support_task_ids", "task_ids", "evidence_task_ids"):
                    raw = edit.get(field, [])
                    raw = [raw] if isinstance(raw, (str, int)) else raw
                    claimed = {str(value) for value in raw} if isinstance(raw, (list, tuple)) else set()
                    discarded.update(claimed - training_ids)
                    if field in edit:
                        edit[field] = sorted(claimed & training_ids)
                edits.append(edit)
            changes = [row["audit"]["mean_improvement"] for row in self.store.records("cam_gate")[-2:]]
            decision = compute_evidence_budget(edits, total_failures=sum(row["hard"] == 0 for row in self.training_rows),
                min_budget=min(2, kwargs["max_edits"]), max_budget=kwargs["max_edits"],
                min_support_tasks=self.cam_cfg["cam_budget_min_support_tasks"], recent_score_changes=changes)
            self.store.append(f"cam_budget:{self.step}", "cam_budget", {"step": self.step,
                **asdict(decision), "discarded_ids": sorted(discarded)})
            patch = {**patch, "edits": decision.eligible_edits}
            kwargs["max_edits"] = decision.budget
            if not decision.budget:
                self.selected = []
                return {"edits": []}
        ranked = self._stage("rank", rank_and_select, skill, patch, **kwargs)
        self.selected = ranked.get("edits", [])
        return ranked

    def apply(self, skill, patch):
        return apply_patch_with_report(skill, patch)

    def _selection(self, skill):
        event = self.store.get("selection:" + digest(skill))
        if event is None:
            raise InfrastructureFailure("Missing per-task validation evidence")
        return self.store.read_artifact(event["artifact_hash"])["rows"]

    def evaluate_gate(self, **kwargs):
        old = self.store.get(f"native_gate:{self.step}")
        if old:
            return GateResult(**old["gate"])
        if not self.cam:
            result = evaluate_gate(**kwargs)
        else:
            from .vendor.cam.selection_guard import decide_cam_update, indexed_scores
            before, candidate, best = (self._selection(kwargs[name]) for name in ("current_skill", "candidate_skill", "best_skill"))
            result, audit = decide_cam_update(candidate_skill=kwargs["candidate_skill"], current_skill=kwargs["current_skill"],
                best_skill=kwargs["best_skill"], current_results=before, candidate_results=candidate, best_results=best,
                best_step=kwargs["best_step"], global_step=self.step, cfg=self.cam_cfg)
            drift = self.drift.observe(result.current_score, result.best_score, self.step)
            if drift["rolled_back"]:
                result = GateResult(result.action, result.best_skill, result.best_score,
                                    result.best_skill, result.best_score, result.best_step)
            old_scores, new_scores = indexed_scores(before), indexed_scores(candidate)
            types = {row.get("task_type", "overall") for row in self.training_rows}
            self.memory.add_rejected_step(failure_patterns=[str(row.get("task_description", "")) + " " + str(row.get("fail_reason", ""))
                    for row in self.training_rows if row["hard"] == 0], rejected_edits=[canonical(edit) for edit in self.selected],
                score_change=kwargs["cand_hard"]-kwargs["current_score"], benchmark="spreadsheetbench",
                task_type=next(iter(types)) if len(types) == 1 else "mixed", epoch=1, step=self.step,
                kind="accepted" if result.action in {"accept", "accept_new_best"} else "rejected" if result.action == "reject" else "inconclusive",
                skill_before_hash=digest(kwargs["current_skill"]), skill_after_hash=digest(kwargs["candidate_skill"]),
                supporting_task_ids=[identity for identity in old_scores if old_scores[identity] != new_scores[identity]])
            self.store.append(f"cam_gate:{self.step}", "cam_gate", {"step": self.step, "audit": audit, "drift": drift})
        self.store.append(f"native_gate:{self.step}", "native_gate", {"step": self.step, "gate": asdict(result)})
        return result

    def summary(self):
        return {"kind": self.cfg["control_kind"], "task_executions": sum(row["tasks"] for row in self.store.records("rollout_started")),
                "training_observations": len(self.store.records("observation")), "cache_hits": len(self.store.records("cache_hit")),
                "gates": len(self.store.records("native_gate")), "no_change": len(self.store.records("native_no_change"))}
