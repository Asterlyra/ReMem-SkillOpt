"""Reproduce provider-envelope handling with synthetic responses and no network."""
# ruff: noqa: E402 -- repository bootstrap precedes project imports with a shared venv

import argparse
import hashlib
import json
import os
import socket
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from openai import OpenAI

SOURCE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE_ROOT))

from skillopt.model import azure_openai as backend
from skillopt.remem.call_policy import ResearchCallPolicy, use_call_policy
from skillopt.remem.transport_audit import audited_call, client_options, summarize


def audit(output: Path):
    if not Path(backend.__file__).resolve().is_relative_to(SOURCE_ROOT):
        raise RuntimeError("Offline fixture imported a backend outside its source checkout")
    output.mkdir(parents=True, exist_ok=False)
    result = {"scope": "synthetic_offline_provider_contract", "real_model_calls": 0, "network_attempts": 0,
              "backend_sha256": hashlib.sha256(Path(backend.__file__).read_bytes()).hexdigest(), "cases": {}}

    def deny_network(*args, **kwargs):
        result["network_attempts"] += 1
        raise RuntimeError("Offline fixture forbids network")

    fixtures = {
        "valid_reply": {"id": "synthetic", "model": "synthetic-model", "object": "chat.completion", "created": 0,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        "data_inspection_error": {"error": {"code": "data_inspection_failed", "type": "upstream_error",
                                            "message": "Synthetic fixture; no real task or provider message"}},
    }
    with patch.object(socket.socket, "connect", deny_network), patch.object(socket, "create_connection", deny_network):
        for name, body in fixtures.items():
            path = output / (name + "_transport.jsonl")
            with TemporaryDirectory(prefix="fixture-", dir=output) as temp, patch.dict(os.environ, {"REMEM_TRANSPORT_AUDIT_PATH": str(path.resolve())}):
                options = client_options("optimizer")
                hooks = options["http_client"].event_hooks
                options["http_client"].close()
                mocked = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body, request=request)), event_hooks=hooks)
                observed = {"http_status": 200}
                with OpenAI(base_url="https://offline.invalid/v1", api_key="offline-fixture-placeholder", http_client=mocked, max_retries=0) as client:
                    with patch.object(backend.time, "sleep", lambda seconds: None):
                        try:
                            with use_call_policy(ResearchCallPolicy(Path(temp), timeout_s=240)):
                                with audited_call("offline_fixture"):
                                    text, _ = backend._chat_impl(client, "synthetic-model", "Synthetic system", "Synthetic user", 16, 3, "offline_fixture", timeout=240)
                            observed.update(status="returned", content_is_fixture=text == "{}")
                        except Exception as error:
                            observed.update(status="raised", error_type=type(error).__name__,
                                            provider_error_category=getattr(error, "category", None),
                                            typed_message=str(error) if str(error) == "LLM call failed: TypeError" else None)
                records = [json.loads(line) for line in path.read_text().splitlines() if line]
                observed["transport"] = summarize(path)
                observed["provider_contracts"] = [r["response_contract"] for r in records if r["kind"] == "usage"]
                result["cases"][name] = observed
    assert result["network_attempts"] == 0
    assert result["cases"]["valid_reply"]["transport"]["http_attempts"] == 1
    # This is a diagnostic of the CURRENT baseline, not the desired behavior.
    result["baseline_repeated_blocked_response"] = result["cases"]["data_inspection_error"]["transport"]["http_attempts"] == 3
    result["known_block_stopped_on_first_response"] = (
        result["cases"]["data_inspection_error"]["transport"]["http_attempts"] == 1
        and result["cases"]["data_inspection_error"]["error_type"] == "NonRetryableProviderError"
    )
    (output / "metadata.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    audit(parser.parse_args().output.resolve())
