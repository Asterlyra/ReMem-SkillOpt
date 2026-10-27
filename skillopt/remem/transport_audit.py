"""Opt-in, metadata-only HTTP and usage audit for OpenAI-compatible runs."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import httpx

from .provider_contract import provider_error, provider_error_category

_WRITE_LOCK = threading.Lock()
_CALL: ContextVar[tuple[str, str] | None] = ContextVar("remem_audit_call", default=None)
_RESPONSE_ID: ContextVar[str | None] = ContextVar("remem_audit_response_id", default=None)


def current_call_id() -> str | None:
    current = _CALL.get()
    return current[1] if current else None


@contextmanager
def audited_call(stage: str, call_id: str | None = None):
    previous = _CALL.get()
    identity = call_id or uuid.uuid4().hex
    nested = previous is not None and previous[1] == identity
    token = _CALL.set((stage, identity))
    response_token = _RESPONSE_ID.set(None)
    started = time.monotonic()
    error_type = None
    try:
        yield
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        path = audit_path()
        if path is not None and not nested:
            _write(path, {"kind": "logical_completion", "stage": stage, "call_id": identity,
                          "elapsed_s": time.monotonic() - started, "error_type": error_type})
        _RESPONSE_ID.reset(response_token)
        _CALL.reset(token)


def audit_path() -> Path | None:
    raw = os.environ.get("REMEM_TRANSPORT_AUDIT_PATH", "").strip()
    return Path(raw).resolve() if raw else None


def _write(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK, path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def client_options(role: str) -> dict[str, Any]:
    """Disable hidden SDK retries and observe each actual HTTP request."""
    path = audit_path()
    if path is None:
        return {}

    def on_request(request: httpx.Request) -> None:
        identity = uuid.uuid4().hex
        current = _CALL.get()
        from .call_policy import active_policy
        policy = active_policy()
        if policy is not None:
            policy.request(role, current[1] if current else None, identity)
        request.extensions["remem_audit_id"] = identity
        request.extensions["remem_audit_start"] = time.monotonic()
        try:
            body_bytes = len(request.content)
        except httpx.RequestNotRead:
            body_bytes = None
        _write(path, {"kind": "request", "id": identity, "role": role,
                      "stage": current[0] if current else None,
                      "call_id": current[1] if current else None,
                      "host": request.url.host, "path": request.url.path,
                      "method": request.method, "time_ns": time.time_ns(), "body_bytes": body_bytes})

    def on_response(response: httpx.Response) -> None:
        request = response.request
        _RESPONSE_ID.set(request.extensions.get("remem_audit_id"))
        _write(path, {"kind": "response", "id": request.extensions.get("remem_audit_id"),
                      "role": role, "status": response.status_code,
                      "elapsed_s": time.monotonic() - request.extensions.get("remem_audit_start", time.monotonic())})

    return {"http_client": httpx.Client(event_hooks={"request": [on_request], "response": [on_response]}),
            "max_retries": 0}


def record_usage(role: str, stage: str, response: Any) -> None:
    path = audit_path()
    if path is None:
        return
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if prompt is None and usage is not None:
        prompt = getattr(usage, "input_tokens", None)
    if completion is None and usage is not None:
        completion = getattr(usage, "output_tokens", None)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(prompt_details, "cached_tokens", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    choices = getattr(response, "choices", None) or []
    error = provider_error(response)
    error_category = provider_error_category(response)
    current = _CALL.get()
    _write(path, {"kind": "usage", "role": role, "stage": stage,
                  "id": _RESPONSE_ID.get(), "call_id": current[1] if current else None,
                  "response_model": getattr(response, "model", None),
                  "response_contract": {"has_model": bool(getattr(response, "model", None)),
                                        "has_choices": bool(choices), "provider_error_present": bool(error),
                                        "provider_error_category": error_category},
                  "finish_reason": getattr(choices[0], "finish_reason", None) if choices else None,
                  "prompt_tokens": prompt, "completion_tokens": completion,
                  "total_tokens": getattr(usage, "total_tokens", None),
                  "cached_prompt_tokens": cached,
                  "reasoning_tokens": getattr(completion_details, "reasoning_tokens", None)})


def summarize(path: Path) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    requests = [record for record in records if record["kind"] == "request"]
    responses = [record for record in records if record["kind"] == "response"]
    usage = [record for record in records if record["kind"] == "usage"]
    completions = [record for record in records if record["kind"] == "logical_completion"]
    call_ids = {record.get("call_id") for record in requests}
    timing_complete = (bool(requests) and None not in call_ids and len(completions) == len(call_ids)
                       and {record["call_id"] for record in completions} == call_ids)
    ok_responses = sum(200 <= record["status"] < 300 for record in responses)
    successful_ids = {record["id"] for record in responses if 200 <= record["status"] < 300}
    complete = (bool(requests) and len(requests) == len(responses) and len(usage) == ok_responses
                and ok_responses == len(responses)
                and None not in successful_ids
                and {record.get("id") for record in usage} == successful_ids
                and all(record["prompt_tokens"] is not None and record["completion_tokens"] is not None
                        for record in usage))
    numeric_usage_ids = {record.get("id") for record in usage
                         if type(record.get("prompt_tokens")) is int and record["prompt_tokens"] >= 0
                         and type(record.get("completion_tokens")) is int and record["completion_tokens"] >= 0}
    numeric_usage_ids.discard(None)
    provider_error_ids = {record.get("id") for record in usage
                          if record.get("response_contract", {}).get("provider_error_present") is True}
    provider_error_ids.discard(None)
    return {"http_attempts": len(requests), "http_responses": len(responses),
            "logical_calls": len({record["call_id"] for record in requests if record.get("call_id")})
            if all(record.get("call_id") for record in requests) else None,
            "retry_attempts": (len(requests) - len({record["call_id"] for record in requests}))
            if all(record.get("call_id") for record in requests) else None,
            "request_stages": {stage: sum(record.get("stage") == stage for record in requests)
                               for stage in sorted({record["stage"] for record in requests if record.get("stage")})},
            "http_elapsed_s_sum": sum(record["elapsed_s"] for record in responses),
            "http_response_headers_elapsed_s_sum": sum(record["elapsed_s"] for record in responses),
            "logical_timing_complete": timing_complete,
            "logical_call_elapsed_s_sum": sum(record["elapsed_s"] for record in completions) if timing_complete else None,
            "successful_http_responses": ok_responses,
            "reported_usage_responses": len(usage), "usage_complete": complete,
            "responses_with_numeric_usage": sum(record.get("id") in numeric_usage_ids for record in responses),
            "responses_without_numeric_usage": sum(record.get("id") not in numeric_usage_ids for record in responses),
            "provider_error_http_responses": sum(record.get("id") in provider_error_ids for record in responses),
            "known_prompt_tokens": sum(record["prompt_tokens"] for record in usage if record["prompt_tokens"] is not None),
            "known_completion_tokens": sum(record["completion_tokens"] for record in usage if record["completion_tokens"] is not None),
            "prompt_tokens": sum(record["prompt_tokens"] for record in usage) if complete else None,
            "completion_tokens": sum(record["completion_tokens"] for record in usage) if complete else None,
            "cached_prompt_tokens": (sum(record["cached_prompt_tokens"] for record in usage)
                                     if complete and all(record["cached_prompt_tokens"] is not None for record in usage)
                                     else None),
            "error_statuses": [record["status"] for record in responses if record["status"] >= 400],
            "roles": {role: sum(record["role"] == role for record in requests)
                      for role in sorted({record["role"] for record in requests})}}
