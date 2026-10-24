from __future__ import annotations

import json
import shutil

import pytest

from skillopt.remem import study


def test_task_plan_is_fixed_stratified_and_repeats_only_training():
    items = [{"id": str(i), "instruction_type": "a" if i < 60 else "b"} for i in range(80)]
    plan = study.task_plan(items, 42)
    assert plan == study.task_plan(items, 42)
    assert plan != study.task_plan(items, 43)
    assert len(plan) == 6 and all(len(batch) == 20 for batch in plan)
    first = [t for batch in plan[:4] for t in batch]
    repeated = [t for batch in plan[4:] for t in batch]
    assert len(set(first)) == 80 and len(set(repeated)) == 40
    assert set(repeated) <= set(first)
    assert sum(int(t) < 60 for t in repeated) == 30


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for name in ("configs/remem/core.yaml", "configs/spreadsheetbench/default.yaml", "configs/_base_/default.yaml"):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(study.ROOT / name, dest)
    rows = [{"id": str(i), "instruction_type": "cell"} for i in range(80)]
    for split, values in (("train", rows), ("val", [{"id": str(i)} for i in range(80, 120)]), ("test", [{"id": "private-test"}])):
        study.write_json(root / "data/spreadsheetbench_split" / split / "items.json", values)
    workbook = root / "data/runtime/example.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"synthetic payload fingerprint")
    study.write_json(root / "data/remem_data_manifest.json", {"runtime_data_root": "data/runtime", "runtime_files": {"example.xlsx": study.file_hash(workbook)}})
    monkeypatch.setattr(study, "source_files", lambda root: sorted((root / "configs").rglob("*.yaml")))
    monkeypatch.setattr(study.subprocess, "check_output", lambda *args, **kwargs: "mock-head" if "rev-parse" in args[0] else "")
    directory = study.prepare("test-v1", root=root)
    return root, directory


def test_prepare_only_freezes_core_development_and_report_is_readonly(prepared):
    root, directory = prepared
    result = study.verify(directory, root=root)
    assert result["core_runs"] == 12 and result["formal_ready"] is False
    before = {str(p): p.stat().st_mtime_ns for p in directory.rglob("*") if p.is_file()}
    report = study.report(directory)
    assert all(r["status"] == "not_started" and r["tokens"] is None for r in report["runs"])
    assert before == {str(p): p.stat().st_mtime_ns for p in directory.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        study.prepare("test-v1", root=root)
    configs = [json.loads(p.read_text()) for p in (directory / "configs").glob("*.json")]
    for seed in (42, 43, 44):
        schedules = [c["remem"]["task_schedule"] for c in configs if c["seed"] == seed]
        assert all(s == schedules[0] for s in schedules)
    assert all(c["eval_test"] is False for c in configs)


@pytest.mark.parametrize("target", ["source", "config", "payload", "split", "freeze"])
def test_verify_refuses_mutations(prepared, target):
    root, directory = prepared
    paths = {"source": root / "configs/remem/core.yaml", "config": next((directory / "configs").glob("*.json")),
             "payload": root / "data/runtime/example.xlsx", "split": root / "data/spreadsheetbench_split/train/items.json",
             "freeze": directory / "freeze.json"}
    path = paths[target]
    path.write_bytes(path.read_bytes() + b"\nchanged")
    with pytest.raises(ValueError):
        study.verify(directory, root=root)


def test_report_reads_existing_ledger_without_writing(prepared):
    from skillopt.remem.store import EventStore
    root, directory = prepared
    name = json.loads((directory / "freeze.json").read_text())["run_order"][0]
    store = EventStore(directory / "runs" / name / "remem", {})
    store.append("call", "rollout_started", {"tasks": 20})
    before = store.path.read_bytes()
    report = study.report(directory)
    row = next(r for r in report["runs"] if r["run"] == name)
    assert row["status"] == "incomplete" and row["task_executions"] == 20
    assert row["tokens"] is None and row["http_attempts"] is None
    assert store.path.read_bytes() == before
