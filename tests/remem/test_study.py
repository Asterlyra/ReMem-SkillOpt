from __future__ import annotations

import json
import shutil

import pytest

from skillopt.remem import study
from skillopt.remem.controls import BudgetedControlAdapter, FixedScheduleLoader


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
    core = root / "configs/remem/core.yaml"
    core.write_text(core.read_text(encoding="utf-8").replace(
        "data/spreadsheetbench_remem_400", "data/runtime"), encoding="utf-8")
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


def test_prepare_alternate_data_profile(prepared):
    root, _ = prepared
    profile = root / "configs/remem/alternate.yaml"
    profile.write_text("_base_: core.yaml\nenv:\n  data_root: data/other-runtime\n"
                       "  split_dir: data/other-split\n", encoding="utf-8")
    shutil.copytree(root / "data/spreadsheetbench_split", root / "data/other-split")
    other = root / "data/other-runtime"
    other.mkdir(parents=True)
    (other / "example.xlsx").write_bytes(b"other synthetic payload")
    manifest = root / "data/other-manifest.json"
    study.write_json(manifest, {"runtime_data_root": "data/other-runtime",
                                "runtime_files": {"example.xlsx": study.file_hash(other / "example.xlsx")}})
    directory = study.prepare("test-alt", root=root, config_path=profile, data_manifest_path=manifest)
    assert study.verify(directory, root=root)["status"] == "passed"
    frozen = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    assert frozen["data_manifest_path"] == "data/other-manifest.json"
    assert frozen["split_dir"] == "data/other-split"


def test_skillopt_control_uses_same_frozen_task_schedule(prepared):
    root, _ = prepared
    directory = study.prepare("test-control", root=root, include_skillopt_controlled=True)
    assert study.verify(directory, root=root)["external_runs"] == 3
    core = json.loads((directory / "configs/core_00_42.json").read_text(encoding="utf-8"))
    control = json.loads((directory / "configs/skillopt_controlled_42.json").read_text(encoding="utf-8"))
    assert control["control_task_schedule"] == core["remem"]["task_schedule"]
    assert control["train_size"] == 120 and "remem" not in control

    class Base:
        train_items = [{"id": str(i)} for i in range(80)]

    batches = FixedScheduleLoader(Base(), control["control_task_schedule"], 42).plan_train_epoch(
        epoch=1, steps_per_epoch=6, accumulation=1, batch_size=20, seed=42)
    assert [[str(row["id"]) for row in batch.payload] for batch in batches] == control["control_task_schedule"]


def test_control_rollout_budget_cache_and_interruption(tmp_path):
    class Adapter:
        calls = 0

        def rollout(self, env, skill, out_dir, **kwargs):
            self.calls += 1
            folder = tmp_path / "train"
            folder.mkdir()
            results = [{"id": row["id"], "hard": 0} for row in env]
            (folder / "results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in results))
            return results

    base = Adapter()
    adapter = BudgetedControlAdapter(base, tmp_path, task_limit=2)
    env = [{"id": "a"}, {"id": "b"}]
    assert len(adapter.rollout(env, "skill", str(tmp_path / "train"))) == 2
    assert len(adapter.rollout(env, "skill", str(tmp_path / "train"))) == 2
    assert base.calls == 1
    events = adapter._records()
    assert [row["kind"] for row in events] == ["start", "done", "cache"]
    with pytest.raises(RuntimeError, match="budget exhausted"):
        adapter.rollout(env, "changed skill", str(tmp_path / "other"))
    class Broken:
        def rollout(self, env, skill, out_dir, **kwargs):
            raise OSError("simulated interruption")

    interrupted = BudgetedControlAdapter(Broken(), tmp_path / "interrupted", task_limit=2)
    with pytest.raises(OSError):
        interrupted.rollout(env, "skill", str(tmp_path / "interrupted" / "train"))
    with pytest.raises(RuntimeError, match="requires reconciliation"):
        interrupted.rollout(env, "skill", str(tmp_path / "interrupted" / "train"))


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
