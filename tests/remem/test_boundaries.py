from __future__ import annotations

from dataclasses import asdict

import pytest

from skillopt.remem.budget import select
from skillopt.remem.config import ReMemConfig
from skillopt.remem.evaluation import PairedBootstrapGate
from skillopt.remem.runtime import classify
from skillopt.remem.types import RepairAttempt


def test_misspelled_upstream_control_is_not_silently_dropped():
    from skillopt.config import flatten_config
    with pytest.raises(ValueError, match="Unknown"):
        flatten_config({"remem": {}, "optimizer": {"use_slow_updat": False}})


@pytest.mark.parametrize("reason", ["llm-call-failed: Timeout", "task-timeout-600s", "no-test-cases", "unexpected: OSError"])
def test_infrastructure_not_mistaken_for_task_failure(reason):
    assert classify({"id": "x", "hard": 0, "fail_reason": reason})[0] == "infra_failure"


def test_executor_timeout_and_evaluator_load_errors_are_infrastructure():
    for field, message in [("error", "timeout after 30s"), ("reason", "load error: missing workbook")]:
        assert classify({"hard": 0, "llm_ok": True, "cases": [{field: message}]})[0] == "infra_failure"
    assert classify({"hard": 0, "llm_ok": True, "fail_reason": "eval-mismatch: wrong value"})[0] == "failure"


def test_gate_pairs_ids_not_list_position_and_has_three_outcomes():
    gate = PairedBootstrapGate(samples=1000)
    before = [{"id": str(i), "hard": 0} for i in range(10)]
    after = [{"id": str(i), "hard": 1} for i in reversed(range(10))]
    assert gate.compare(before, after)["action"] == "accept"
    assert gate.compare(after, before)["action"] == "reject"
    assert gate.compare(before, before)["action"] == "inconclusive"
    with pytest.raises(ValueError):
        gate.compare(before, after[:-1])
    with pytest.raises(ValueError):
        gate.compare(before, before + before[:1])
    with pytest.raises(ValueError):
        gate.compare(before, [{**r, "llm_ok": False} for r in after])


def test_conflicts_duplicates_and_edit_budget_remain_auditable():
    edits = [{"op": "replace", "target": "a", "content": "b"},
             {"op": "replace", "target": "a", "content": "c"},
             {"op": "replace", "target": "a", "content": "b"},
             {"op": "append", "target": "", "content": "d"}]
    chosen, audit = select(edits, 1, repair=False)
    assert chosen == edits[:1]
    assert [r["decision"] for r in audit] == ["selected", "conflicting_anchor_alternative", "duplicate", "edit_budget"]


@pytest.mark.parametrize("change", [{"typo": True}, {"memory": "false"}, {"max_edits": 0},
                                    {"max_edits": 5}, {"confidence": 1}, {"enabled": "false"}])
def test_invalid_config_rejected(change):
    with pytest.raises(ValueError):
        ReMemConfig.parse({"remem": change})


@pytest.mark.parametrize("key", ["eval_test", "use_meta_skill", "use_slow_update", "use_skill_aware_reflection"])
def test_auxiliary_channels_and_tests_disabled(key):
    with pytest.raises(ValueError):
        ReMemConfig.parse({"remem": {}, key: True})


def test_attempt_never_claims_per_edit_causal_effect():
    attempt = asdict(RepairAttempt("a", 1, "before", "candidate", ("case",), ("p1", "p2"), "accept", True))
    assert attempt["attribution"] == "update_bundle"
    assert attempt["semantic_diagnosis_status"] == "unverified"
