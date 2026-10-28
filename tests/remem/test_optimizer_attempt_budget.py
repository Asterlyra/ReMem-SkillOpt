"""Regression test: the ReMem proposal call must honour the frozen attempt budget.

The frozen protocol documents "at most 3 attempts" per optimizer call, the call
policy caps retries at `research_limits.max_attempts`, and every sibling optimizer
path passes 3. This path passed 1, so a single transient timeout aborted an entire
arm: on 2026-10-28 a 178 KB proposal request hit the 240 s client timeout and
killed repair_only_42 at step 3 after steps 1-2 had completed.
"""
from __future__ import annotations

from types import SimpleNamespace

from skillopt.remem import runtime as runtime_module
from skillopt.remem.runtime import OPTIMIZER_ATTEMPTS, ReMemRuntime


class _FakeStore:
    def __init__(self):
        self.records_written: list[tuple[str, str, dict]] = []

    def records(self, kind: str):
        return []

    def append(self, event_id: str, kind: str, payload: dict):
        self.records_written.append((event_id, kind, payload))
        return True

    def artifact(self, value: dict) -> str:
        return "0" * 64


class _CapturingRuntime(ReMemRuntime):
    """Minimal stand-in that records the arguments of the optimizer call."""

    def __init__(self):
        self.options = SimpleNamespace(optimizer_calls=40, optimizer_output_tokens=16384)
        self.store = _FakeStore()
        self.step = 1
        self.captured: list[dict] = []

    def chat(self, **kwargs):
        self.captured.append(kwargs)
        return '{"status":"no_change","reason":"x","proposals":[]}', {}


def test_optimizer_attempt_budget_matches_the_frozen_protocol():
    # The frozen freeze.json sets research_limits.max_attempts = 3.
    assert OPTIMIZER_ATTEMPTS == 3
    assert runtime_module.OPTIMIZER_ATTEMPTS == 3


def test_proposal_call_requests_the_full_attempt_budget():
    instance = _CapturingRuntime()
    instance._call("system prompt", "user payload")
    assert len(instance.captured) == 1
    call = instance.captured[0]
    assert call["retries"] == OPTIMIZER_ATTEMPTS
    assert call["retries"] > 1, "a single attempt lets one timeout abort a whole arm"
    assert call["stage"] == "remem_proposal"


def test_empty_optimizer_reply_is_still_an_infrastructure_failure():
    class _Empty(_CapturingRuntime):
        def chat(self, **kwargs):
            self.captured.append(kwargs)
            return "", {}

    instance = _Empty()
    try:
        instance._call("system prompt", "user payload")
    except Exception as exc:  # noqa: BLE001 - asserting the failure class name
        assert type(exc).__name__ == "InfrastructureFailure"
    else:
        raise AssertionError("empty optimizer content must not be accepted")
