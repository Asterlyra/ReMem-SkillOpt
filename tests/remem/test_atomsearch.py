from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from skillopt.remem.atomsearch import DEFAULTS, AtomSearchRuntime, ProposalInvalid, SearchTree, parse_proposal
from skillopt.remem.types import canonical


def reply(contents=("CHECK", "PRESERVE")):
    return canonical({"status": "proposals", "reason": "Separate evidence-backed rules",
        "specifications": [{"id": str(i), "support_ids": ["t0"], "counterexample_ids": ["t1"],
            "hypothesis": "Missing scan " + text, "scope": "numeric conversion",
            "expected_effect": "preserve valid input", "operation_rationale": "add one missing check"}
            for i, text in enumerate(contents)],
        "edits": [{"criterion_id": str(i), "operation": "add", "rule_id": "document_end", "content": text}
                  for i, text in enumerate(contents)]})


OBSERVATIONS = [{"task_id": "t0", "outcome": "failure"}, {"task_id": "t1", "outcome": "success"}]


@pytest.mark.parametrize("mutation", ["foreign", "wrong_outcome", "shared_spec", "non_atomic", "empty", "orphan", "extra_spec_key"])
def test_reject_unsubstantiated_or_non_atomic_edits(mutation):
    obj = json.loads(reply())
    if mutation == "foreign":
        obj["specifications"][0]["support_ids"] = ["v0"]
    elif mutation == "wrong_outcome":
        obj["specifications"][0]["counterexample_ids"] = ["t0"]
    elif mutation == "shared_spec":
        obj["edits"][1]["criterion_id"] = "0"
    elif mutation == "non_atomic":
        obj["edits"][0]["content"] = "a\nb"
    elif mutation == "empty":
        obj["specifications"][0]["scope"] = ""
    elif mutation == "extra_spec_key":
        obj["specifications"][0]["criterion_id"] = obj["specifications"][0]["id"]
    else:
        obj["edits"].pop()
    with pytest.raises(ProposalInvalid):
        parse_proposal(canonical(obj), "initial", OBSERVATIONS, DEFAULTS)


def test_structural_validation_deduplicates_but_does_not_claim_semantics():
    candidates, _ = parse_proposal(reply(("CHECK", "CHECK")), "initial", OBSERVATIONS, DEFAULTS)
    assert len(candidates) == 1
    assert candidates[0]["specification"]["support_ids"] == ["t0"]


def test_search_retains_weaker_ancestor_and_separates_robust_from_best():
    tree = SearchTree("root", .5, DEFAULTS)
    weak = tree.attach(0, "weak", .25, [])
    assert tree.select() == weak  # PW initially allows only one root child.
    best = tree.attach(weak, "best", 1., [])
    assert tree.nodes[0].visits == 2
    assert tree.nodes[weak].visits == 2
    assert tree.nodes[weak].expansions == 1
    assert tree.nodes[0].expansion_reward == -.25
    assert tree.nodes[0].reward == .25
    assert tree.recommend() == best
    tree.attach(0, "sibling", .9, [])
    assert tree.recommend() == best


def test_max_depth_and_branch_capacity():
    tree = SearchTree("root", 0., {**DEFAULTS, "max_depth": 1, "branch_factor": 1})
    tree.attach(0, "child", .2, [])
    assert tree.select() is None


class Adapter:
    def __init__(self, composition_score=1):
        self.calls = []
        self.composition_score = composition_score

    def build_env_from_batch(self, batch, **kwargs):
        assert batch.split in {"train", "val"}
        return batch.payload

    def rollout(self, env, skill, directory, **kwargs):
        self.calls.append((tuple(r["id"] for r in env), skill))
        return [{"id": r["id"], "hard": (int(r["id"] == "t1") if r["id"].startswith("t") else
                self.composition_score if "PRESERVE" in skill else 0),
                 "llm_ok": True, "fail_reason": "incomplete scan"} for r in env]


def make_runtime(tmp_path, chat=None, **options):
    skill = tmp_path / "initial.md"
    skill.write_text("initial", encoding="utf-8")
    cfg = {"out_root": str(tmp_path / "run"), "skill_init": str(skill), "seed": 42, "batch_size": 2,
           "control_kind": "atomsearch_budgeted", "control_task_schedule": [["t0", "t1"]],
           "atomsearch": {"attempts": 2}, "research_limits": {"task_executions": 20}}
    cfg.update(options)
    loader = SimpleNamespace(train_items=[{"id": "t0"}, {"id": "t1"}], val_items=[{"id": "v0"}, {"id": "v1"}])
    adapter = Adapter()
    prompts = []
    def generate(**kwargs):
        request = json.loads(kwargs["user"])
        prompts.append(request)
        # Audited current failures must exist before generation.
        assert runtime.store.records("observation")
        if "CHECK" in request["skill"]:
            return canonical({"status": "no_change", "reason": "no evidence", "specifications": [], "edits": []}), {}
        return reply(), {}
    runtime = AtomSearchRuntime(cfg, loader, adapter, chat or generate)
    return runtime, adapter, prompts, loader


def test_contract_invalid_proposal_fails_the_node_not_the_whole_search(tmp_path):
    """A malformed proposal must not destroy a budget-limited search.

    On 2026-10-29 glm returned a specification whose field set was wrong and
    `ProposalInvalid` propagated out of run(), killing the arm at proposal 2 of 30.
    The violation is now recorded and scored as a zero-reward expansion.
    """
    malformed = canonical({"status": "proposals", "reason": "malformed",
                           "specifications": [{"id": "0"}],
                           "edits": [{"criterion_id": "0", "operation": "add",
                                      "rule_id": "document_end", "content": "CHECK"}]})
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        assert runtime.store.records("observation")
        if calls["n"] == 1:
            return malformed, {}
        return reply(), {}

    runtime, adapter, _, _ = make_runtime(tmp_path, chat=flaky)
    result = runtime.run()

    assert result["contract_invalid_proposals"] == 1
    events = runtime.store.records("atom_proposal_invalid")
    assert len(events) == 1
    assert events[0]["cause"] == "specification fields"
    # The search still produced and evaluated a candidate afterwards.
    assert result["nodes"] >= 2
    assert result["status"] != "tree_exhausted" or result["total_steps"] >= 1


def test_real_search_composition_memory_isolation_and_resume(tmp_path):
    runtime, adapter, prompts, loader = make_runtime(tmp_path)
    result = runtime.run()
    assert result["nodes"] == 2 and result["test_executions"] == 0
    assert result["final_selection_hard"] == 1
    assert "PRESERVE" in Path(result["final_skill"]).read_text()
    assert len(adapter.calls) == 5  # baseline, train, primitive, composed, second train
    assert prompts[1]["outcome_memory"]["recent_attempts"][-1]["attribution"] == "update_bundle"
    assert prompts[1]["outcome_memory"]["recent_attempts"][-1]["repairs"] == 2
    assert "v0" not in canonical(prompts) and "v1" not in canonical(prompts)
    before = len(adapter.calls)
    again = AtomSearchRuntime(runtime.cfg, loader, adapter, lambda **kw: pytest.fail("resume called optimizer"))
    assert again.run() == result and len(adapter.calls) == before


def test_tie_keeps_primitive_and_unused_rollout_candidate(tmp_path):
    runtime, adapter, _, _ = make_runtime(tmp_path, atomsearch={"attempts": 1})
    adapter.composition_score = 0
    result = runtime.run()
    assert "CHECK" in Path(result["final_skill"]).read_text()
    assert "PRESERVE" not in Path(result["final_skill"]).read_text()
    checkpoint = runtime.store.read_artifact(runtime.store.records("atom_checkpoint")[-1]["artifact_hash"])
    assert len(checkpoint["nodes"][0]["pool"]) == 1


def test_budget_stops_without_overshoot_and_keeps_evaluated_child(tmp_path):
    runtime, adapter, _, loader = make_runtime(tmp_path, research_limits={"task_executions": 6})
    result = runtime.run()
    assert result["status"] == "budget_exhausted" and result["task_executions"] == 6
    assert result["nodes"] == 2 and "CHECK" in Path(result["final_skill"]).read_text()
    before = len(adapter.calls)
    assert AtomSearchRuntime(runtime.cfg, loader, adapter, lambda **kw: pytest.fail()).run() == result
    assert len(adapter.calls) == before


def test_bad_proposal_is_recorded_per_node_and_never_silently_becomes_no_change(tmp_path):
    """A contract violation must be auditable, but must not destroy the search.

    Superseded semantics: this used to assert that ProposalInvalid escaped run().
    The arm-level abort was replaced by a recorded, zero-reward node failure on
    2026-10-29, because one malformed glm proposal killed a 30-attempt search.
    What must still hold: it is never treated as a legitimate "no change", it is
    always recorded, and the run reports it.
    """
    runtime, _, _, _ = make_runtime(tmp_path, chat=lambda **kwargs: ("bad JSON", {}))
    result = runtime.run()
    assert runtime.store.records("atom_proposal_invalid")
    assert not runtime.store.records("atom_no_change")
    assert runtime.store.records("observation")
    assert result["contract_invalid_proposals"] >= 1
    assert (runtime.root / "summary.json").exists()


def test_optimizer_service_failure_is_recorded_and_cannot_become_no_change_or_silent_resume(tmp_path):
    def fail(**kwargs):
        raise TimeoutError("synthetic service failure")
    runtime, adapter, _, loader = make_runtime(tmp_path, chat=fail)
    with pytest.raises(TimeoutError):
        runtime.run()
    assert runtime.store.records("optimizer_error")[0]["error_type"] == "TimeoutError"
    assert len(runtime.store.records("observation")) == 2
    assert not runtime.store.records("atom_no_change") and not (runtime.root / "summary.json").exists()
    calls_before = len(adapter.calls)
    again = AtomSearchRuntime(runtime.cfg, loader, adapter, lambda **kwargs: pytest.fail("Unreconciled retry"))
    from skillopt.remem.audit_runtime import InfrastructureFailure
    with pytest.raises(InfrastructureFailure, match="requires reconciliation"):
        again.run()
    assert len(adapter.calls) == calls_before


def test_no_success_counterexample_is_explicit_no_change_without_fabrication(tmp_path):
    runtime, adapter, _, _ = make_runtime(tmp_path, chat=lambda **kw: pytest.fail("No valid contrast exists"))
    original = adapter.rollout
    def rollout(*args, **kwargs):
        rows = original(*args, **kwargs)
        return [{**row, "hard": 0} for row in rows]
    adapter.rollout = rollout
    result = runtime.run()
    assert result["nodes"] == 1 and result["refills"] == 2
    assert len(runtime.store.records("atom_no_change")) == 2
    assert len(runtime.store.records("observation")) == 4
    assert not runtime.store.records("optimizer_started")
