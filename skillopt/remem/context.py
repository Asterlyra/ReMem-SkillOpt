"""Bounded training-only memory; the disabled strategy never reads the ledger."""
from __future__ import annotations

from dataclasses import asdict

from .store import EventStore
from .types import canonical


class NoMemory:
    def retrieve(self, **kwargs) -> list[dict]:
        return []


class FailureMemory:
    def __init__(self, store: EventStore, top_k: int = 3, max_attempts: int = 2, character_cap: int = 12000):
        self.store, self.top_k, self.max_attempts, self.character_cap = store, top_k, max_attempts, character_cap

    def retrieve(self, *, task_ids: set[str], skill_hash: str, before_step: int) -> list[dict]:
        cases = [c for c in self.store.cases(skill_hash, before_step=before_step)
                 if c.status != "resolved_observed" and c.task_id in task_ids]
        cases.sort(key=lambda c: (c.task_id not in task_ids, -c.seen_count, -c.last_seen_step, c.case_id))
        attempts = [a for a in self.store.records("attempt") if a["step"] < before_step]
        groups = []
        for case in cases:
            event = self.store.get(case.event_ids[-1])
            observation = {**event, "trace": self.store.read_artifact(event["artifact_hash"])["trace"]}
            history = [{k: a[k] for k in ("attempt_id", "step", "skill_before_hash", "skill_candidate_hash", "gate_action", "adopted", "attribution", "edits")}
                       for a in attempts if case.case_id in a["case_ids"]][-self.max_attempts:]
            group = {"case": asdict(case), "observation": observation, "attempts": history}
            # A long trace must not silently make a relevant case un-retrievable.
            # Bound each group and preserve exact substrings for evidence quotes.
            group_cap = self.character_cap // self.top_k
            observation["trace_context_truncated"] = False
            while len(canonical(group)) > group_cap and len(observation["trace"]) >= 8:
                excess = len(canonical(group)) - group_cap
                observation["trace"] = observation["trace"][:max(0, len(observation["trace"])-max(excess, 1))]
                observation["trace_context_truncated"] = True
            if len(observation["trace"]) < 8:
                continue
            if len(canonical([*groups, group])) > self.character_cap:
                continue
            groups.append(group)
            if len(groups) == self.top_k:
                break
        return groups
