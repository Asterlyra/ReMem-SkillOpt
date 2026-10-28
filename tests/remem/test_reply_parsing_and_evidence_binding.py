"""Regression tests for the two protocol defects found in the 2026-10-28 study.

Defect 1: an optimizer reply wrapping a valid JSON object in a Markdown fence was
recorded as `invalid_json`, discarding the whole proposal step. Observed in 2/3
R-only proposal steps and in 2/2 gateway probes.

Defect 2: a real quote paired with the wrong `artifact_hash` discarded the entire
proposal. Because the check is all-or-nothing over the reference list, proposals
citing the most evidence were the most likely to be lost.
"""
from __future__ import annotations

import json

import pytest

from skillopt.remem.evidence import validate_proposal
from skillopt.remem.proposals import JsonProposalStrategy, classify_reply
from skillopt.remem.store import EventStore
from skillopt.remem.types import FailureEvent, canonical, digest


def reply(status="proposals", reason="A real recurring pattern.", proposals=None):
    payload = {
        "status": status,
        "reason": reason,
        "proposals": proposals if proposals is not None else [{"proposal_id": "p1"}],
    }
    return json.dumps(payload)


def fenced(text: str) -> str:
    return "```json\n" + text + "\n```"


# --- Defect 1: Markdown fence tolerance -------------------------------------


def test_bare_json_is_still_reported_as_bare():
    parsed, mode = classify_reply(reply())
    assert parsed["status"] == "proposals"
    assert mode == "bare_json"


def test_fenced_json_is_parsed_and_reported_as_fenced():
    parsed, mode = classify_reply(fenced(reply()))
    assert parsed["status"] == "proposals"
    assert mode == "fenced_json"


def test_no_json_is_reported_rather_than_silently_accepted():
    parsed, mode = classify_reply("I could not analyse these failures.")
    assert parsed is None
    assert mode == "no_json"


def test_strategy_accepts_a_fenced_reply_instead_of_discarding_the_step():
    strategy = JsonProposalStrategy(True, lambda prompt, user: fenced(reply()), 4)
    result = strategy.propose("# Rules\nInspect data.\n", [], [])
    assert result.status == "proposals"
    assert result.parse == "fenced_json"
    assert len(result.proposals) == 1


def test_strategy_still_records_invalid_json_for_unparseable_output():
    strategy = JsonProposalStrategy(True, lambda prompt, user: "no json here", 4)
    result = strategy.propose("# Rules\nInspect data.\n", [], [])
    assert result.status == "proposal_invalid"
    assert result.reason == "invalid_json"
    assert result.parse == "no_json"


# --- Defect 2: evidence re-binding ------------------------------------------


def observe(store, event_id, quote, task_id="t1", kind="wrong_value", step=1):
    artifact = store.artifact({"trace": quote})
    event = FailureEvent(event_id, "run", task_id, "v1", step, "failure", kind, artifact)
    store.observe(event)
    return event


def bound_proposal(event, skill, **overrides):
    body = {
        "proposal_id": "p1",
        "skill_before_hash": digest(skill),
        "failure_case_ids": [digest(canonical([event.task_id, event.failure_kind]))],
        "evidence_refs": [{
            "event_id": event.event_id,
            "artifact_hash": event.artifact_hash,
            "quote": "only inspected the first five rows",
        }],
        "diagnosis": "missing_check",
        "target_rule_id": "document_end",
        "repair_operator": "ADD_CHECK",
        "patch": {"op": "append", "target": "", "content": "CHECK every populated cell."},
        "expected_observation": "Checks all populated cells before conversion.",
        "preserve_cases": [],
    }
    body.update(overrides)
    return body


def test_misbound_artifact_hash_is_rebound_to_the_trace_that_holds_the_quote(tmp_path):
    store = EventStore(tmp_path, {})
    skill = "# Rules\nInspect data.\n"
    cited = observe(store, "e1", "only inspected the first five rows")
    other = observe(store, "e2", "a completely different trace", task_id="t2")

    p = bound_proposal(cited, skill)
    # Model paired the real quote with the wrong artifact: the clerical slip seen in
    # both arms' step 3, where 1/6 and 2/7 refs failed and killed the proposal.
    p["evidence_refs"][0]["artifact_hash"] = other.artifact_hash

    repairs = validate_proposal(p, skill, {cited.event_id, other.event_id}, store)
    assert len(repairs) == 1
    assert repairs[0]["to"]["event_id"] == cited.event_id
    assert repairs[0]["to"]["artifact_hash"] == cited.artifact_hash
    assert p["evidence_refs"][0]["event_id"] == cited.event_id
    assert p["evidence_refs"][0]["artifact_hash"] == cited.artifact_hash


def test_clean_proposal_reports_no_repairs(tmp_path):
    store = EventStore(tmp_path, {})
    skill = "# Rules\nInspect data.\n"
    cited = observe(store, "e1", "only inspected the first five rows")
    assert validate_proposal(bound_proposal(cited, skill), skill, {cited.event_id}, store) == []


def test_fabricated_quote_is_still_rejected(tmp_path):
    store = EventStore(tmp_path, {})
    skill = "# Rules\nInspect data.\n"
    cited = observe(store, "e1", "only inspected the first five rows")
    p = bound_proposal(cited, skill)
    p["evidence_refs"][0]["quote"] = "an observation that was never recorded"
    with pytest.raises(ValueError, match="quote"):
        validate_proposal(p, skill, {cited.event_id}, store)


def test_ambiguous_quote_is_rejected_rather_than_guessed(tmp_path):
    store = EventStore(tmp_path, {})
    skill = "# Rules\nInspect data.\n"
    first = observe(store, "e1", "only inspected the first five rows", task_id="t1")
    second = observe(store, "e2", "only inspected the first five rows", task_id="t2", kind="wrong_value")
    p = bound_proposal(first, skill)
    # Point at a third artifact that does NOT hold the quote while two visible
    # traces both do, so re-binding cannot choose without guessing.
    decoy = store.artifact({"trace": "unrelated trace"})
    p["evidence_refs"][0]["artifact_hash"] = decoy
    with pytest.raises(ValueError, match="multiple"):
        validate_proposal(p, skill, {first.event_id, second.event_id}, store)


def test_rebinding_never_pulls_evidence_from_outside_the_permitted_context(tmp_path):
    store = EventStore(tmp_path, {})
    skill = "# Rules\nInspect data.\n"
    hidden = observe(store, "hidden", "a trace the optimizer was not shown")
    visible = observe(store, "e1", "only inspected the first five rows")
    p = bound_proposal(visible, skill)
    # Quote exists only in the hidden trace; it must not be rescued by re-binding.
    p["evidence_refs"][0]["quote"] = "a trace the optimizer was not shown"
    with pytest.raises(ValueError):
        validate_proposal(p, skill, {visible.event_id}, store)


def test_out_of_context_reference_still_reports_the_context_boundary(tmp_path):
    store = EventStore(tmp_path, {})
    skill = "# Rules\nInspect data.\n"
    outside = observe(store, "outside", "only inspected the first five rows")
    p = bound_proposal(outside, skill)
    with pytest.raises(ValueError, match="context"):
        validate_proposal(p, skill, set(), store)
