"""Run-scoped, persistent optimizer limits shared by every research arm."""
from __future__ import annotations

import inspect
import threading
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from .store import EventStore
from .transport_audit import audited_call


class CallPolicyError(RuntimeError):
    """A typed research failure; provider text and credentials are not included."""


class CallBudgetExceeded(CallPolicyError):
    pass


class ResearchCallPolicy:
    def __init__(self, root: Path, *, optimizer_calls=80, output_tokens=16384,
                 max_attempts=3, timeout_s=120, target_calls=400):
        limits = dict(optimizer_calls=optimizer_calls, output_tokens=output_tokens,
                      max_attempts=max_attempts, timeout_s=timeout_s, target_calls=target_calls)
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise ValueError("Call limits must be positive integers")
        self.limits = limits
        self.store = EventStore(root / "remem/calls", limits)
        self.lock = threading.RLock()
        self.assert_healthy()
        finished = {row["call_id"] for row in self.store.records("done") + self.store.records("error")}
        if any(row["call_id"] not in finished for row in self.store.records("start")):
            raise CallPolicyError("Unfinished optimizer call requires reconciliation before resume")

    def assert_healthy(self):
        if self.store.records("error") or self.store.records("format_error") or self.store.records("limit"):
            raise CallPolicyError("Research call failure is recorded; do not silently continue or retry the run")

    def reserve(self, stage):
        with self.lock:
            self.assert_healthy()
            if len(self.store.records("start")) >= self.limits["optimizer_calls"]:
                self.store.append(uuid.uuid4().hex, "limit", {"resource": "optimizer_calls"})
                raise CallBudgetExceeded("Optimizer logical-call limit reached")
            identity = uuid.uuid4().hex
            self.store.append(identity, "start", {"call_id": identity, "stage": stage, "time_ns": time.time_ns()})
            return identity

    def request(self, role, call_id, request_id):
        with self.lock:
            self.assert_healthy()
            if not call_id:
                raise CallPolicyError("HTTP call lacks a logical identity")
            prior = self.store.records("http")
            attempts = sum(row["call_id"] == call_id for row in prior)
            target_ids = {row["call_id"] for row in prior if row["role"] == "target"}
            if (attempts >= self.limits["max_attempts"] or
                    (role == "target" and call_id not in target_ids and len(target_ids) >= self.limits["target_calls"])):
                self.store.append(uuid.uuid4().hex, "limit", {"resource": "http_attempts_or_target_calls"})
                raise CallBudgetExceeded("HTTP attempt or target-call limit reached")
            self.store.append(request_id, "http", {"call_id": call_id, "role": role})


_ACTIVE: ResearchCallPolicy | None = None


def active_policy():
    return _ACTIVE


@contextmanager
def use_call_policy(policy: ResearchCallPolicy):
    global _ACTIVE
    if _ACTIVE is not None:
        raise CallPolicyError("Only one research run may use this process")
    _ACTIVE = policy
    try:
        yield policy
        policy.assert_healthy()
    finally:
        _ACTIVE = None


def assert_calls_healthy():
    if _ACTIVE is not None:
        _ACTIVE.assert_healthy()


def record_format_error(stage):
    if _ACTIVE is not None:
        _ACTIVE.store.append(uuid.uuid4().hex, "format_error", {"stage": stage})


def fail_research_stage(stage):
    if _ACTIVE is not None:
        _ACTIVE.assert_healthy()
        record_format_error(stage)
        raise CallPolicyError("Invalid optimizer output in " + stage)


def budget_optimizer(function):
    signature = inspect.signature(function)

    @wraps(function)
    def wrapper(*args, **kwargs):
        policy = _ACTIVE
        if policy is None:
            return function(*args, **kwargs)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        stage = bound.arguments["stage"]
        bound.arguments["max_completion_tokens"] = min(bound.arguments["max_completion_tokens"], policy.limits["output_tokens"])
        bound.arguments["retries"] = min(bound.arguments["retries"], policy.limits["max_attempts"])
        bound.arguments["timeout"] = min(bound.arguments["timeout"] or policy.limits["timeout_s"], policy.limits["timeout_s"])
        identity, started = policy.reserve(stage), time.monotonic()
        try:
            with audited_call(stage, identity):
                result = function(*bound.args, **bound.kwargs)
            if not result[0] or not (result[0] if isinstance(result[0], str) else getattr(result[0], "content", "")):
                raise CallPolicyError("Optimizer returned empty content")
        except Exception as exc:
            policy.store.append(identity + ":error", "error", {"call_id": identity, "stage": stage,
                                "error_type": type(exc).__name__, "elapsed_s": time.monotonic() - started})
            raise
        policy.store.append(identity + ":done", "done", {"call_id": identity, "stage": stage,
                            "elapsed_s": time.monotonic() - started})
        return result
    return wrapper
