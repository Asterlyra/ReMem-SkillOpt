import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from skillopt.envs.spreadsheetbench import codegen_agent
from skillopt.model import azure_openai as backend
from skillopt.remem.call_policy import ResearchCallPolicy, budget_optimizer, use_call_policy
from skillopt.remem.provider_contract import (
    NonRetryableProviderError,
    ProviderResponseError,
    provider_error_category,
    validate_research_provider_response,
)
from skillopt.remem.transport_audit import audited_call, client_options, summarize


@pytest.fixture
def mocked_client(tmp_path, monkeypatch):
    monkeypatch.setenv("REMEM_TRANSPORT_AUDIT_PATH", str(tmp_path / "transport.jsonl"))
    monkeypatch.setattr(backend.time, "sleep", lambda _: None)

    def build(bodies):
        options = client_options("optimizer")
        hooks = options["http_client"].event_hooks
        options["http_client"].close()
        pending = iter(bodies)
        observed = []

        def respond(request):
            observed.append(request.url.path)
            return httpx.Response(200, request=request, json=next(pending))

        client = OpenAI(base_url="https://offline.invalid/v1", api_key="offline-placeholder",
                        max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(respond), event_hooks=hooks))
        return client, observed

    return build


def blocked(code="data_inspection_failed"):
    return {"error": {"code": code, "type": "upstream_error", "message": "PRIVATE_PROVIDER_TEXT"}}


def valid():
    return {"id": "fixture", "model": "fixture", "object": "chat.completion", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}


def invoke(client, messages=False, responses=False):
    deployment = "gpt-5.3-codex" if responses else "fixture"
    if messages:
        return backend._chat_messages_impl(client, deployment, [{"role": "user", "content": "fixture"}], 16, 3, "analyst", timeout=240)
    return backend._chat_impl(client, deployment, "fixture", "fixture", 16, 3, "analyst", timeout=240)


@pytest.mark.parametrize("messages", [False, True])
@pytest.mark.parametrize("responses", [False, True])
@pytest.mark.parametrize("code", ["data_inspection_failed", "DataInspectionFailed"])
def test_known_http200_provider_block_stops_before_response_parsing(tmp_path, mocked_client, messages, responses, code):
    client, seen = mocked_client([blocked(code)])
    with client, use_call_policy(ResearchCallPolicy(tmp_path)):
        with audited_call("analyst"), pytest.raises(NonRetryableProviderError) as caught:
            invoke(client, messages, responses)
    assert len(seen) == 1
    assert caught.value.category == "data_inspection_failed"
    path = tmp_path / "transport.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    contract = next(row["response_contract"] for row in records if row["kind"] == "usage")
    assert contract["provider_error_category"] == "data_inspection_failed"
    assert "PRIVATE_PROVIDER_TEXT" not in path.read_text() + str(caught.value)
    summary = summarize(path)
    assert summary["http_attempts"] == 1 and summary["retry_attempts"] == 0
    assert summary["provider_error_http_responses"] == 1
    assert summary["responses_with_numeric_usage"] == 0
    assert summary["responses_without_numeric_usage"] == 1
    assert summary["usage_complete"] is False and summary["prompt_tokens"] is None


def test_transient_provider_error_can_retry_then_succeed(tmp_path, mocked_client):
    client, seen = mocked_client([blocked("service_unavailable"), valid()])
    with client, use_call_policy(ResearchCallPolicy(tmp_path)), audited_call("analyst"):
        text, _ = invoke(client)
    assert text == "OK" and len(seen) == 2
    summary = summarize(tmp_path / "transport.jsonl")
    assert summary["retry_attempts"] == 1 and summary["provider_error_http_responses"] == 1
    assert summary["responses_with_numeric_usage"] == 1
    assert summary["responses_without_numeric_usage"] == 1
    assert summary["usage_complete"] is False


def test_unknown_provider_errors_remain_bounded_and_do_not_expose_raw_code(tmp_path, mocked_client):
    client, seen = mocked_client([blocked("PRIVATE_CODE")] * 3)
    with client, use_call_policy(ResearchCallPolicy(tmp_path)):
        with audited_call("analyst"), pytest.raises(ProviderResponseError) as caught:
            invoke(client)
    assert len(seen) == 3 and caught.value.category == "unclassified"
    assert "PRIVATE" not in (tmp_path / "transport.jsonl").read_text() + str(caught.value)


@pytest.mark.parametrize("responses", [False, True])
def test_target_codegen_records_typed_block_without_retries(tmp_path, mocked_client, responses):
    client, seen = mocked_client([blocked()])
    with client, use_call_policy(ResearchCallPolicy(tmp_path)):
        with pytest.raises(NonRetryableProviderError):
            codegen_agent._chat_call(client, "gpt-5.3-codex" if responses else "fixture",
                                    [{"role": "user", "content": "fixture"}], 16)
    assert len(seen) == 1


def test_known_error_is_preserved_in_durable_optimizer_failure(tmp_path, mocked_client):
    client, seen = mocked_client([blocked()])

    @budget_optimizer
    def call(system, user, max_completion_tokens=16, retries=3, stage="analyst", timeout=None):
        return backend._chat_impl(client, "fixture", system, user, max_completion_tokens, retries, stage, timeout=timeout)

    policy = ResearchCallPolicy(tmp_path)
    with client, pytest.raises(NonRetryableProviderError):
        with use_call_policy(policy):
            call("fixture", "fixture")
    assert len(seen) == 1
    assert policy.store.records("error")[0]["provider_error_category"] == "data_inspection_failed"
    assert not policy.store.records("done")


def test_error_takes_precedence_over_plausible_reply_and_is_research_scoped(tmp_path):
    response = SimpleNamespace(model="fixture", choices=[object()], usage=None,
                               model_extra={"error": {"code": "data_inspection_failed"}})
    validate_research_provider_response(response)  # no research policy: upstream behavior stays intact
    with use_call_policy(ResearchCallPolicy(tmp_path)), pytest.raises(NonRetryableProviderError):
        validate_research_provider_response(response)
    response = SimpleNamespace(model_extra={}, error=SimpleNamespace(code="DataInspectionFailed"))
    assert provider_error_category(response) == "data_inspection_failed"
