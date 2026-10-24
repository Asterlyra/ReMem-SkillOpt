"""Native SkillOpt external control with the frozen ReMem task schedule."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from skillopt.datasets.base import BatchSpec


class FixedScheduleLoader:
    """Delegate dataset loading while replacing only the native epoch planner."""

    def __init__(self, base, schedule: list[list[str]], seed: int):
        if len(schedule) != 6 or any(len(batch) != 20 for batch in schedule):
            raise ValueError("SkillOpt control requires the six fixed 20-task batches")
        self.base, self.schedule, self.seed = base, schedule, seed

    def __getattr__(self, name):
        return getattr(self.base, name)

    def get_train_size(self) -> int:
        return sum(map(len, self.schedule))

    def plan_train_epoch(self, *, epoch: int, steps_per_epoch: int, accumulation: int,
                         batch_size: int, seed: int, **kwargs) -> list[BatchSpec]:
        if (epoch, steps_per_epoch, accumulation, batch_size, seed) != (1, 6, 1, 20, self.seed):
            raise ValueError("SkillOpt control schedule/config mismatch")
        train_items = {str(row["id"]): row for row in self.base.train_items}
        if len(train_items) != 80:
            raise ValueError("SkillOpt control requires 80 distinct training tasks")
        flattened = [task for batch in self.schedule for task in batch]
        if set(flattened) != set(train_items) or len(set(flattened[:80])) != 80 or len(set(flattened[80:])) != 40:
            raise ValueError("SkillOpt control schedule does not match the training registry")
        return [BatchSpec("train", "train", seed + index, 20, [train_items[task] for task in batch])
                for index, batch in enumerate(self.schedule)]


def bind_native_control(adapter, schedule: list[list[str]], seed: int) -> None:
    if not hasattr(adapter, "dataloader"):
        raise ValueError("Native SkillOpt control requires a dataset adapter")
    adapter.dataloader = FixedScheduleLoader(adapter.dataloader, schedule, seed)


class BudgetedControlAdapter:
    """Count native control task executions before each uncached rollout."""

    def __init__(self, base, out_root: Path, task_limit: int = 400):
        self.base, self.out_root, self.task_limit = base, out_root.resolve(), task_limit
        self.journal = self.out_root / "remem/control_rollouts.jsonl"
        self._lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.base, name)

    def _records(self) -> list[dict]:
        if not self.journal.exists():
            return []
        return [json.loads(line) for line in self.journal.read_text(encoding="utf-8").splitlines() if line]

    def _append(self, row: dict) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
            stream.flush()

    def rollout(self, env, skill_content: str, out_dir: str, **kwargs):
        folder = Path(out_dir).resolve()
        if not folder.is_relative_to(self.out_root):
            raise ValueError("Control rollout path escapes run directory")
        ids = [str(row["id"]) for row in env]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Control rollout has duplicate or empty task IDs")
        key = hashlib.sha256(json.dumps([folder.relative_to(self.out_root).as_posix(),
                                         hashlib.sha256(skill_content.encode()).hexdigest(), ids],
                                        separators=(",", ":")).encode()).hexdigest()
        with self._lock:
            events = self._records()
            previous = [row for row in events if row["key"] == key]
            if previous:
                if not any(row["kind"] == "done" for row in previous):
                    raise RuntimeError("Interrupted control rollout requires reconciliation")
                if (folder / "results.jsonl").is_file():
                    results = [json.loads(line) for line in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
                    if len(results) == len(ids) and {str(row["id"]) for row in results} == set(ids):
                        self._append({"kind": "cache", "key": key, "tasks": len(ids)})
                        return results
                raise RuntimeError("Completed control rollout cache is incomplete")
            spent = sum(row["tasks"] for row in events if row["kind"] == "start")
            if spent + len(ids) > self.task_limit:
                raise RuntimeError("SkillOpt control task budget exhausted")
            self._append({"kind": "start", "key": key, "tasks": len(ids)})
        result = self.base.rollout(env, skill_content, out_dir, **kwargs)
        if len(result) != len(ids) or {str(row["id"]) for row in result} != set(ids):
            raise RuntimeError("Control rollout returned incomplete or mismatched tasks")
        with self._lock:
            self._append({"kind": "done", "key": key, "tasks": len(ids)})
        return result
