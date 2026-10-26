from types import SimpleNamespace

import httpx

from skillopt.remem.transport_audit import audited_call, client_options, record_usage, summarize


def test_transport_audit_counts_attempts_without_request_secrets(tmp_path, monkeypatch):
    import json
    path = tmp_path / "transport.jsonl"
    monkeypatch.setenv("REMEM_TRANSPORT_AUDIT_PATH", str(path))
    options = client_options("target")
    assert options["max_retries"] == 0
    client = options["http_client"]
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions",
                            headers={"Authorization": "Bearer secret"}, content=b"private prompt")
    with audited_call("rollout", "one-call"):
        client.event_hooks["request"][0](request)
        client.event_hooks["response"][0](httpx.Response(200, request=request))
        response = SimpleNamespace(model="deepseek-flash", usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=4, total_tokens=14,
            prompt_tokens_details=SimpleNamespace(cached_tokens=3)))
        record_usage("target", "rollout", response)
    summary = summarize(path)
    assert summary["http_attempts"] == 1
    assert summary["usage_complete"] is True
    assert summary["prompt_tokens"] == 10
    assert summary["cached_prompt_tokens"] == 3
    assert summary["logical_timing_complete"] is True
    assert summary["logical_call_elapsed_s_sum"] >= 0
    assert "secret" not in path.read_text(encoding="utf-8")
    assert "private prompt" not in path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert next(row for row in records if row["kind"] == "request")["body_bytes"] == len(b"private prompt")
    client.close()


def test_provider_error_metadata_keeps_only_allowlisted_category_and_missing_usage(tmp_path, monkeypatch):
    import json

    path = tmp_path / "metadata.jsonl"
    monkeypatch.setenv("REMEM_TRANSPORT_AUDIT_PATH", str(path))
    for code in ("context_length_exceeded", "private-secret-value"):
        response = SimpleNamespace(model=None, choices=None, usage=None,
                                   model_extra={"error": {"code": code, "message": "private provider body"}})
        record_usage("optimizer", "analyst", response)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["response_contract"]["provider_error_category"] for row in rows] == ["context_length_exceeded", "unclassified"]
    assert all(row["response_contract"]["provider_error_present"] and not row["response_contract"]["has_choices"] for row in rows)
    assert "private" not in path.read_text()
    assert summarize(path)["prompt_tokens"] is None and summarize(path)["usage_complete"] is False


def test_nested_audit_identity_has_one_completion_and_errors_have_timing(tmp_path, monkeypatch):
    import json

    import pytest
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("REMEM_TRANSPORT_AUDIT_PATH", str(path))
    with pytest.raises(TimeoutError):
        with audited_call("outer", "same"):
            with audited_call("inner", "same"):
                raise TimeoutError("private provider body")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["error_type"] == "TimeoutError"
    assert "private provider body" not in path.read_text()


def test_missing_usage_remains_missing(tmp_path, monkeypatch):
    path = tmp_path / "transport.jsonl"
    monkeypatch.setenv("REMEM_TRANSPORT_AUDIT_PATH", str(path))
    client = client_options("optimizer")["http_client"]
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    client.event_hooks["request"][0](request)
    client.event_hooks["response"][0](httpx.Response(200, request=request))
    assert summarize(path)["prompt_tokens"] is None
    assert summarize(path)["usage_complete"] is False
    client.close()


def test_retry_is_counted_and_failed_attempt_keeps_total_usage_unknown(tmp_path, monkeypatch):
    path = tmp_path / "transport.jsonl"
    monkeypatch.setenv("REMEM_TRANSPORT_AUDIT_PATH", str(path))
    client = client_options("optimizer")["http_client"]
    for status in (429, 200):
        with audited_call("remem_proposal", "one-logical-call"):
            request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
            client.event_hooks["request"][0](request)
            client.event_hooks["response"][0](httpx.Response(status, request=request))
            if status == 200:
                response = SimpleNamespace(model="deepseek-flash", usage=SimpleNamespace(
                    prompt_tokens=10, completion_tokens=4, total_tokens=14))
                record_usage("optimizer", "remem_proposal", response)
    summary = summarize(path)
    assert summary["http_attempts"] == 2
    assert summary["logical_calls"] == 1
    assert summary["retry_attempts"] == 1
    assert summary["request_stages"] == {"remem_proposal": 2}
    assert summary["usage_complete"] is False
    assert summary["prompt_tokens"] is None and summary["known_prompt_tokens"] == 10
    client.close()
