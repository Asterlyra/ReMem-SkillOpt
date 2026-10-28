"""Probe HTTP error and queue-resume boundaries with synthetic local fixtures."""
# ruff: noqa: E402 -- repository bootstrap precedes project imports with a shared venv

import argparse
import hashlib
import json
import os
import socket
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import OpenAI

SOURCE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE_ROOT))

from scripts.remem import run_diagnostic_queue as queue
from skillopt.model import azure_openai as backend
from skillopt.remem.call_policy import ResearchCallPolicy, use_call_policy
from skillopt.remem.transport_audit import audited_call, client_options, summarize


def queue_probe(folder, prior=None, transport=None):
    folder.mkdir()
    (folder / "freeze.json").write_text(json.dumps({"study_id": "synthetic", "run_order": ["first", "second"]}))
    if prior:
        (folder / "queue.json").write_text(json.dumps(prior))
    if transport:
        target = folder / "runs/first/remem/transport.jsonl"
        target.parent.mkdir(parents=True)
        target.write_bytes(transport.read_bytes())
    started = []

    def launch(args, **kwargs):
        name = args[args.index("--name") + 1]
        started.append(name)
        return SimpleNamespace(pid=100, wait=lambda: 1 if name == "first" else 0)

    original = (folder / "queue.json").read_bytes() if prior else None
    with patch.object(queue, "verify", lambda _: None), patch.object(queue, "active_study_processes", lambda _: []), \
         patch.object(queue, "report", lambda _: {"runs": [{"run": "first", "status": "incomplete"}, {"run": "second", "status": "development_completed"}]}), \
         patch.object(queue.subprocess, "Popen", launch), patch.object(queue.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)):
        try:
            exit_code = queue.main(folder, folder / "nonexistent-synthetic-key-file", resume_unstarted=prior is not None)
        except RuntimeError as error:
            if not prior or "new frozen study/version" not in str(error):
                raise
            return {"mocked_arms_started": started, "resume_rejected": True,
                    "original_queue_unchanged": (folder / "queue.json").read_bytes() == original,
                    "backup_created": bool(list(folder.glob("queue.before_resume_*")))}
    saved = json.loads((folder / "queue.json").read_text())
    return {"mocked_arms_started": started, "exit_code": exit_code, "status": saved["status"],
            "retained_original_failed_arm": prior is None or saved["runs"][0] == prior["runs"][0]}


def audit(output):
    if not Path(backend.__file__).resolve().is_relative_to(SOURCE_ROOT):
        raise RuntimeError("Offline audit imported a backend outside its source checkout")
    output.mkdir(exist_ok=False, parents=True)
    result = {"scope": "synthetic_recovery_boundary_audit", "real_model_calls": 0,
              "real_child_processes": 0, "network_attempts": 0, "http_cases": {}}

    def deny_network(*args, **kwargs):
        result["network_attempts"] += 1
        raise AssertionError("No network allowed")

    with patch.object(socket.socket, "connect", deny_network), patch.object(socket, "create_connection", deny_network):
        for status in (200, 400, 403, 429, 500):
            transport = output / f"http_{status}.jsonl"
            with TemporaryDirectory(dir=output) as temp, patch.dict(os.environ, {"REMEM_TRANSPORT_AUDIT_PATH": str(transport)}):
                options = client_options("optimizer")
                hooks = options["http_client"].event_hooks
                options["http_client"].close()
                body = {"error": {"code": "data_inspection_failed", "type": "upstream_error", "message": "Synthetic private message"}}
                mocked = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body, request=request)), event_hooks=hooks)
                with OpenAI(base_url="https://offline.invalid/v1", api_key="offline-placeholder", max_retries=0, http_client=mocked) as client, patch.object(backend.time, "sleep", lambda _: None):
                    try:
                        with use_call_policy(ResearchCallPolicy(Path(temp), timeout_s=240)), audited_call("synthetic"):
                            backend._chat_impl(client, "synthetic", "synthetic", "synthetic", 16, 3, "synthetic", timeout=240)
                    except Exception as error:
                        observed = {"exception_type": type(error).__name__, "safe_category": getattr(error, "category", None)}
                    else:
                        raise AssertionError("Synthetic error was accepted")
                observed["transport"] = summarize(transport)
            observed["queue_after_failure"] = queue_probe(output / f"queue_http_{status}", transport=transport)
            assert observed["exception_type"] == "NonRetryableProviderError"
            assert observed["safe_category"] == "data_inspection_failed"
            assert observed["transport"]["http_attempts"] == 1
            assert observed["transport"]["provider_error_http_responses"] == 1
            assert observed["transport"]["prompt_tokens"] is None
            assert observed["queue_after_failure"]["mocked_arms_started"] == ["first"]
            assert observed["queue_after_failure"]["status"] == "stopped_provider_contract_failure"
            result["http_cases"][str(status)] = observed
        result["resume_cases"] = {}
        for status in ("stopped_provider_contract_failure", "stopped_malformed_provider_response"):
            previous = {"study_id": "synthetic", "status": status, "pid": 999999,
                        "selected_run_order": ["first", "second"], "provider_error_categories": ["data_inspection_failed"],
                        "runs": [{"run": "first", "status": "failed", "exit_code": 1}], "final_test_released": False}
            resume = queue_probe(output / ("queue_" + status), prior=previous)
            assert resume["resume_rejected"] and resume["original_queue_unchanged"]
            assert not resume["mocked_arms_started"] and not resume["backup_created"]
            result["resume_cases"][status] = resume
    assert result["network_attempts"] == 0
    source = SOURCE_ROOT
    result["source_hashes"] = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in (
        "skillopt/remem/provider_contract.py", "scripts/remem/run_diagnostic_queue.py", "skillopt/model/azure_openai.py",
        "skillopt/envs/spreadsheetbench/codegen_agent.py", "skillopt/remem/transport_audit.py")}
    (output / "metadata.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    audit(parser.parse_args().output.resolve())
