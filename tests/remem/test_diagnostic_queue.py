from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts.remem import audit_medium, run_diagnostic_queue


def test_report_retains_missing_model_and_usage_without_sorting_none_with_strings(tmp_path, monkeypatch):
    split = tmp_path / "split/val"
    split.mkdir(parents=True)
    (split / "items.json").write_text("[]")
    (tmp_path / "freeze.json").write_text(
        json.dumps({"study_id": "fixture", "git_head": "fixture", "split_dir": str(split.parent)})
    )
    folder = tmp_path / "runs/arm/remem"
    folder.mkdir(parents=True)
    with sqlite3.connect(folder / "ledger.sqlite3") as db:
        db.execute("CREATE TABLE records (seq INTEGER PRIMARY KEY, kind TEXT, payload TEXT)")
        db.execute(
            "INSERT INTO records(kind,payload) VALUES (?,?)",
            ("cam_budget", json.dumps({"budget": 2, "reason": "legacy_event_without_step"})),
        )
    records = []
    for number, model in enumerate(("glm", None)):
        identity = str(number)
        records.extend(
            [
                {"kind": "request", "id": identity, "role": "optimizer", "stage": "analyst", "call_id": identity},
                {"kind": "response", "id": identity, "role": "optimizer", "status": 200, "elapsed_s": 0.1},
                {
                    "kind": "usage",
                    "id": identity,
                    "role": "optimizer",
                    "call_id": identity,
                    "response_model": model,
                    "finish_reason": "stop" if model else None,
                    "prompt_tokens": 10 if model else None,
                    "completion_tokens": 20 if model else None,
                    "cached_prompt_tokens": None,
                },
                {"kind": "logical_completion", "call_id": identity, "elapsed_s": 0.1},
            ]
        )
    (folder / "transport.jsonl").write_text("\n".join(json.dumps(r) for r in records))
    monkeypatch.setattr(
        audit_medium, "report", lambda _: {"runs": [{"run": "arm", "status": "incomplete", "task_executions": 0}]}
    )
    audit_medium.audit(tmp_path)
    row = json.loads((tmp_path / "operational_audit.json").read_text())["runs"][0]
    assert row["response_models_by_role"]["optimizer"] == ["glm"]
    assert row["response_model_missing_by_role"]["optimizer"] == 1
    assert row["transport"]["usage_complete"] is False
    assert row["transport"]["prompt_tokens"] is None and row["transport"]["known_prompt_tokens"] == 10
    assert row["cam_budget_reasons"] == [{"step": None, "reason": "legacy_event_without_step", "budget": 2}]


@pytest.mark.parametrize("reporting_exit", [0, 1])
@pytest.mark.parametrize("previous_status", ["running", "completed_with_failures", "stopped_authentication_failure"])
def test_explicit_resume_starts_only_unstarted_arms_and_records_reporter_failures(
    tmp_path, monkeypatch, reporting_exit, previous_status
):
    (tmp_path / "freeze.json").write_text(
        json.dumps({"study_id": "fixture", "run_order": ["complete", "failed", "pending"]})
    )
    progress = {
        "study_id": "fixture",
        "status": previous_status,
        "pid": 999999,
        "runs": [
            {"run": "complete", "status": "finished", "exit_code": 0},
            {"run": "failed", "status": "failed", "exit_code": 1},
        ],
    }
    (tmp_path / "queue.json").write_text(json.dumps(progress))
    monkeypatch.setattr(run_diagnostic_queue, "verify", lambda _: None)
    monkeypatch.setattr(run_diagnostic_queue, "active_study_processes", lambda _: [])
    monkeypatch.setattr(
        run_diagnostic_queue, "report", lambda _: {"runs": [{"run": "pending", "status": "development_completed"}]}
    )
    monkeypatch.setattr(
        run_diagnostic_queue.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=reporting_exit)
    )
    started = []

    def launch(args, **kwargs):
        started.append(args[args.index("--name") + 1])
        return SimpleNamespace(pid=42, wait=lambda: 0)

    monkeypatch.setattr(run_diagnostic_queue.subprocess, "Popen", launch)
    code = run_diagnostic_queue.main(tmp_path, tmp_path / ".env.fake.local", resume_unstarted=True)
    saved = json.loads((tmp_path / "queue.json").read_text())
    assert started == ["pending"]
    assert saved["runs"][:2] == progress["runs"]
    assert len(list(tmp_path.glob("queue.before_resume_*.json"))) == 1
    assert code == reporting_exit
    assert saved["status"] == ("stopped_reporting_failure" if reporting_exit else "completed_with_failures")
    if reporting_exit:
        assert saved["reporting_errors"][0]["exit_code"] == 1


def test_live_process_guard_rejects_duplicate_queue_before_any_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(run_diagnostic_queue, "verify", lambda _: None)
    monkeypatch.setattr(run_diagnostic_queue, "active_study_processes", lambda _: [{"pid": 42}])
    with pytest.raises(RuntimeError, match="still live"):
        run_diagnostic_queue.main(tmp_path, tmp_path / ".env.fake.local")
    assert not (tmp_path / "queue.json").exists()


def test_recovery_subset_does_not_start_other_frozen_methods(tmp_path, monkeypatch):
    (tmp_path / "freeze.json").write_text(json.dumps({"study_id": "fixture", "run_order": ["complete", "failed"]}))
    monkeypatch.setattr(run_diagnostic_queue, "verify", lambda _: None)
    monkeypatch.setattr(run_diagnostic_queue, "active_study_processes", lambda _: [])
    monkeypatch.setattr(
        run_diagnostic_queue, "report", lambda _: {"runs": [{"run": "failed", "status": "development_completed"}]}
    )
    monkeypatch.setattr(run_diagnostic_queue.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    started = []

    def launch(args, **kwargs):
        started.append(args[args.index("--name") + 1])
        return SimpleNamespace(pid=42, wait=lambda: 0)

    monkeypatch.setattr(run_diagnostic_queue.subprocess, "Popen", launch)
    assert run_diagnostic_queue.main(tmp_path, tmp_path / ".env.fake.local", only=["failed"]) == 0
    assert started == ["failed"]
    assert json.loads((tmp_path / "queue.json").read_text())["selected_run_order"] == ["failed"]


@pytest.mark.parametrize(
    "contract", [{"provider_error_category": "context_length_exceeded"},
                 {"provider_error_category": "data_inspection_failed"}, {"has_model": False, "has_choices": False}]
)
def test_nontransient_provider_error_stops_before_next_recovery_arm(tmp_path, monkeypatch, contract):
    (tmp_path / "freeze.json").write_text(json.dumps({"study_id": "fixture", "run_order": ["first", "second"]}))
    folder = tmp_path / "runs/first/remem"
    folder.mkdir(parents=True)
    (folder / "transport.jsonl").write_text(json.dumps({"kind": "usage", "response_contract": contract}))
    monkeypatch.setattr(run_diagnostic_queue, "verify", lambda _: None)
    monkeypatch.setattr(run_diagnostic_queue, "active_study_processes", lambda _: [])
    monkeypatch.setattr(run_diagnostic_queue, "report", lambda _: {"runs": [{"run": "first", "status": "incomplete"}]})
    monkeypatch.setattr(run_diagnostic_queue.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    started = []

    def launch(args, **kwargs):
        started.append(args[args.index("--name") + 1])
        return SimpleNamespace(pid=42, wait=lambda: 1)

    monkeypatch.setattr(run_diagnostic_queue.subprocess, "Popen", launch)
    assert run_diagnostic_queue.main(tmp_path, tmp_path / ".env.fake.local") == 1
    assert started == ["first"]
    status = json.loads((tmp_path / "queue.json").read_text())["status"]
    assert status == (
        "stopped_provider_contract_failure"
        if "provider_error_category" in contract
        else "stopped_malformed_provider_response"
    )


@pytest.mark.parametrize("status", ["stopped_provider_contract_failure", "stopped_malformed_provider_response"])
def test_provider_hold_cannot_be_resumed_or_mutated(tmp_path, monkeypatch, status):
    original = json.dumps({"status": status, "pid": 999999, "runs": [{"run": "failed", "status": "failed"}]})
    path = tmp_path / "queue.json"
    path.write_text(original)
    monkeypatch.setattr(run_diagnostic_queue, "verify", lambda _: None)
    monkeypatch.setattr(run_diagnostic_queue, "active_study_processes", lambda _: [])
    monkeypatch.setattr(run_diagnostic_queue.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(RuntimeError, match="new frozen study/version"):
        run_diagnostic_queue.main(tmp_path, tmp_path / "nonexistent-key-file", resume_unstarted=True)
    assert path.read_text() == original
    assert not list(tmp_path.glob("queue.before_resume_*"))


@pytest.mark.parametrize("http_status", [400, 403, 429, 500])
def test_non2xx_error_category_stops_before_next_arm(tmp_path, monkeypatch, http_status):
    (tmp_path / "freeze.json").write_text(json.dumps({"study_id": "fixture", "run_order": ["first", "second"]}))
    folder = tmp_path / "runs/first/remem"
    folder.mkdir(parents=True)
    (folder / "transport.jsonl").write_text('\n'.join(json.dumps(row) for row in [
        {"kind": "response", "status": http_status},
        {"kind": "provider_error", "provider_error_category": "data_inspection_failed", "status": http_status},
    ]))
    monkeypatch.setattr(run_diagnostic_queue, "verify", lambda _: None)
    monkeypatch.setattr(run_diagnostic_queue, "active_study_processes", lambda _: [])
    monkeypatch.setattr(run_diagnostic_queue, "report", lambda _: {"runs": [{"run": "first", "status": "incomplete"}]})
    monkeypatch.setattr(run_diagnostic_queue.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    started = []
    def launch(args, **kwargs):
        started.append(args[args.index("--name") + 1])
        return SimpleNamespace(pid=42, wait=lambda: 1)
    monkeypatch.setattr(run_diagnostic_queue.subprocess, "Popen", launch)
    assert run_diagnostic_queue.main(tmp_path, tmp_path / "nonexistent-key-file") == 1
    assert started == ["first"]
    saved = json.loads((tmp_path / "queue.json").read_text())
    assert saved["status"] == "stopped_provider_contract_failure"
    assert saved["provider_error_categories"] == ["data_inspection_failed"]
