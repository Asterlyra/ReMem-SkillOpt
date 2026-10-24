from __future__ import annotations

from dataclasses import asdict

import pytest

from skillopt.remem.context import FailureMemory, NoMemory
from skillopt.remem.evidence import validate_proposal
from skillopt.remem.store import EventStore
from skillopt.remem.types import FailureEvent, canonical, digest


def observation(store, name="e1", version="v1", step=1, outcome="failure"):
    artifact = store.artifact({"trace": "only inspected first five rows", "truncated": False})
    event = FailureEvent(name, "run", "t1", version, step, outcome, "wrong_value", artifact)
    store.observe(event)
    return event


def proposal(event, skill="# Rules\nInspect data.\n"):
    return {"proposal_id": "p1", "skill_before_hash": digest(skill),
            "failure_case_ids": [digest(canonical(["t1", "wrong_value"]))],
            "evidence_refs": [{"event_id": event.event_id, "artifact_hash": event.artifact_hash,
                               "quote": "only inspected first five rows"}],
            "diagnosis": "missing_check", "target_rule_id": "document_end", "repair_operator": "ADD_CHECK",
            "patch": {"op": "append", "target": "", "content": "CHECK the full column type."},
            "expected_observation": "Checks all populated cells before conversion.", "preserve_cases": []}


def test_idempotent_events_recovery_and_version_bound_status(tmp_path):
    store = EventStore(tmp_path, {"run": 1})
    event = observation(store)
    store.observe(event)
    assert len(store.records("observation")) == 1
    with pytest.raises(ValueError, match="collision"):
        store.append(event.event_id, "observation", {**asdict(event), "step": 5})
    observation(store, "success", "v1", 2, "success")
    assert store.cases("v1", before_step=3)[0].status == "resolved_observed"
    assert store.cases("v2", before_step=3)[0].status == "unresolved"
    observation(store, "later", "v2", 3)
    reopened = EventStore(tmp_path, {"run": 1})
    assert reopened.cases("v2", before_step=4)[0].status == "reopened"
    assert reopened.cases("v1", before_step=2)[0].status == "unresolved"
    with pytest.raises(ValueError, match="collision"):
        EventStore(tmp_path, {"run": 2})


def test_only_train_can_enter_failure_ledger(tmp_path):
    store = EventStore(tmp_path, {})
    event = observation(store)
    with pytest.raises(ValueError, match="training"):
        store.observe(FailureEvent(**{**asdict(event), "event_id": "val", "source_split": "val"}))


def test_evidence_requires_visible_real_quote_and_exact_version(tmp_path):
    store = EventStore(tmp_path, {})
    event = observation(store)
    p = proposal(event)
    skill = "# Rules\nInspect data.\n"
    validate_proposal(p, skill, {event.event_id}, store)
    with pytest.raises(ValueError, match="context"):
        validate_proposal(p, skill, set(), store)
    with pytest.raises(ValueError, match="version"):
        validate_proposal(p, skill + "changed", {event.event_id}, store)
    p["evidence_refs"][0]["quote"] = "fabricated observation"
    with pytest.raises(ValueError, match="quote"):
        validate_proposal(p, skill, {event.event_id}, store)


def test_memory_respects_time_scope_budget_and_disabled_isolation(tmp_path):
    store = EventStore(tmp_path, {})
    observation(store)
    memory = FailureMemory(store)
    assert memory.retrieve(task_ids={"t1"}, skill_hash="v1", before_step=1) == []
    assert memory.retrieve(task_ids={"different"}, skill_hash="v1", before_step=2) == []
    assert len(memory.retrieve(task_ids={"t1"}, skill_hash="v1", before_step=2)) == 1
    assert FailureMemory(store, character_cap=20).retrieve(task_ids={"t1"}, skill_hash="v1", before_step=2) == []
    assert NoMemory().retrieve(task_ids={"t1"}, skill_hash="v1", before_step=2) == []


def test_long_relevant_trace_is_bounded_instead_of_silently_dropped(tmp_path):
    store = EventStore(tmp_path, {})
    artifact = store.artifact({"trace": "observed data " * 1000})
    store.observe(FailureEvent("e", "run", "t1", "v1", 1, "failure", "wrong_value", artifact))
    groups = FailureMemory(store).retrieve(task_ids={"t1"}, skill_hash="v1", before_step=2)
    assert len(groups) == 1
    assert groups[0]["observation"]["trace_context_truncated"] is True
    assert len(canonical(groups)) <= 12000
