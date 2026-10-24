"""Serializable contracts shared by storage, strategies and the trainer."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FailureEvent:
    event_id: str
    run_id: str
    task_id: str
    skill_hash: str
    step: int
    outcome: str
    failure_kind: str
    artifact_hash: str
    source_split: str = "train"


@dataclass(frozen=True)
class FailureCase:
    case_id: str
    task_id: str
    failure_kind: str
    skill_hash: str
    status: str
    first_seen_step: int
    last_seen_step: int
    seen_count: int
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class RepairAttempt:
    attempt_id: str
    step: int
    skill_before_hash: str
    skill_candidate_hash: str
    case_ids: tuple[str, ...]
    proposal_ids: tuple[str, ...]
    gate_action: str
    adopted: bool
    edits: tuple[dict, ...] = ()
    attribution: str = "update_bundle"
    semantic_diagnosis_status: str = "unverified"


@dataclass
class ProposalResult:
    status: str
    proposals: list[dict] = field(default_factory=list)
    reason: str = ""


class MemoryStrategy(Protocol):
    def retrieve(self, *, task_ids: set[str], skill_hash: str, before_step: int) -> list[dict]: ...


class ProposalStrategy(Protocol):
    def propose(self, skill: str, observations: list[dict], memory: list[dict]) -> ProposalResult: ...


class GateStrategy(Protocol):
    def compare(self, before: list[dict], candidate: list[dict]) -> dict: ...
