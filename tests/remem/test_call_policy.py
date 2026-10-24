from concurrent.futures import ThreadPoolExecutor

import pytest

from skillopt.remem.call_policy import (
    CallBudgetExceeded,
    CallPolicyError,
    ResearchCallPolicy,
    budget_optimizer,
    fail_research_stage,
    use_call_policy,
)
from skillopt.remem.transport_audit import current_call_id


def test_shared_budget_clamping_and_persistent_resume(tmp_path):
    seen = []
    @budget_optimizer
    def chat(system, user, max_completion_tokens=64000, retries=9, stage="merge", timeout=None):
        seen.append((max_completion_tokens, retries, timeout, current_call_id()))
        return "ok", {}
    with use_call_policy(ResearchCallPolicy(tmp_path, optimizer_calls=2)):
        chat("s", "u")
    with pytest.raises(CallPolicyError):
        with use_call_policy(ResearchCallPolicy(tmp_path, optimizer_calls=2)):
            chat("s", "u")
            with pytest.raises(CallBudgetExceeded):
                chat("s", "u")
    assert len(seen) == 2 and seen[0][:3] == (16384, 3, 120)
    assert seen[0][3] != seen[1][3]
    with pytest.raises(CallPolicyError):
        ResearchCallPolicy(tmp_path, optimizer_calls=2)


def test_concurrent_reservations_never_exceed_cap(tmp_path):
    policy = ResearchCallPolicy(tmp_path, optimizer_calls=3)
    def reserve(_):
        try:
            return policy.reserve("reflect")
        except CallPolicyError:
            return None
    with ThreadPoolExecutor(8) as workers:
        values = list(workers.map(reserve, range(12)))
    assert sum(v is not None for v in values) == 3


def test_http_retries_and_target_limit(tmp_path):
    policy = ResearchCallPolicy(tmp_path, target_calls=1, max_attempts=2)
    policy.request("target", "one", "r1")
    policy.request("target", "one", "r2")
    with pytest.raises(CallBudgetExceeded):
        policy.request("target", "two", "r3")
    assert len(policy.store.records("http")) == 2


def test_auxiliary_fallback_and_interrupted_calls_fail_closed(tmp_path):
    with pytest.raises(CallPolicyError):
        with use_call_policy(ResearchCallPolicy(tmp_path)):
            fail_research_stage("merge")
    policy = ResearchCallPolicy(tmp_path / "interrupted")
    policy.reserve("rank")
    with pytest.raises(CallPolicyError, match="Unfinished"):
        ResearchCallPolicy(tmp_path / "interrupted")
