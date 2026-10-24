from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from skillopt.config import flatten_config, load_config
from skillopt.datasets.base import BatchSpec
from skillopt.engine import trainer as engine
from skillopt.remem.runtime import InfrastructureFailure
from skillopt.remem.store import EventStore
from skillopt.remem.types import canonical, digest


class Loader:
    train_items = [{"id": "t1", "instruction": "Synthetic task"}]
    val_items = [{"id": f"v{i}"} for i in range(4)]

    def get_train_size(self):
        return len(self.train_items)

    def make_base_seeds(self, **kwargs):
        return [42, 43]

    def build_eval_batch(self, **kwargs):
        assert kwargs["split"] == "valid_seen", "Final test must never be opened"
        return BatchSpec("eval", "val", 42, 4, self.val_items)


class Adapter:
    def __init__(self, selection="improve", interrupt=False):
        self.loader = Loader()
        self.selection = selection
        self.calls = []
        self.interrupt = interrupt

    def setup(self, cfg):
        pass

    def get_dataloader(self):
        return self.loader

    def requires_ray(self):
        return False

    def build_env_from_batch(self, batch, **kwargs):
        return batch.payload

    def get_task_types(self):
        return []

    def reflect(self, *args, **kwargs):
        raise AssertionError("Legacy reflection/history must not enter core arms")

    def rollout(self, env, skill, out_dir, **kwargs):
        ids = [r["id"] for r in env]
        self.calls.append(ids)
        if self.interrupt and ids == ["t1"]:
            raise RuntimeError("simulated infrastructure interruption")
        rows = []
        for item in env:
            if item["id"] == "t1":
                rows.append({"id": "t1", "hard": 0, "soft": 0, "failure_kind": "wrong_value",
                             "fail_reason": "only inspected first five rows", "llm_ok": True})
            else:
                score = int("CHECK" in skill and self.selection == "improve")
                rows.append({"id": item["id"], "hard": score, "soft": score, "llm_ok": True})
        return rows


@pytest.fixture
def make_run(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline integration attempted network access")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    # Fake-backend runs must not change global model configuration for other tests.
    for name in vars(engine):
        if name.startswith(("configure_", "set_")) and callable(getattr(engine, name)):
            monkeypatch.setattr(engine, name, lambda *args, **kwargs: None)

    def create(repair=True, memory=True, replies="edit", selection="improve", steps=2):
        skill = tmp_path / "initial.md"
        skill.write_text("# Rules\nInspect data.\n", encoding="utf-8")
        cfg = flatten_config(load_config("configs/_base_/default.yaml"))
        cfg.update(out_root=str(tmp_path / "run"), skill_init=str(skill), batch_size=1, train_size=1,
                   num_epochs=1, accumulation=1, seed=42, merge_batch_size=2, analyst_workers=1,
                   edit_budget=2, min_edit_budget=1, lr_scheduler="constant", use_slow_update=False,
                   use_meta_skill=False, use_skill_aware_reflection=False, eval_test=False, sel_env_num=4,
                   test_env_num=0, use_gate=True, skill_update_mode="patch", lr_control_mode="fixed")
        cfg["remem"] = {"repair": repair, "memory": memory, "run_id": "test", "bootstrap_samples": 200,
                        "task_schedule": [["t1"] for _ in range(steps)]}
        prompts = []
        def chat(**kwargs):
            request = json.loads(kwargs["user"])
            prompts.append(request)
            store = EventStore(tmp_path / "run/remem", json.loads(_identity(tmp_path)))
            assert store.records("observation"), "Failure must be durable BEFORE generation"
            if replies == "invalid":
                return "not JSON", {}
            if replies == "empty":
                return "", {}
            if replies == "service_error":
                raise TimeoutError("simulated")
            if replies == "no_change" or "CHECK" in request["skill"]:
                return canonical({"status": "no_change", "reason": "insufficient new evidence", "proposals": []}), {}
            edit = {"op": "append", "target": "", "content": "CHECK all populated cells before conversion."}
            if repair:
                event = request["current_training_observations"][0]
                p = {"proposal_id": "p1", "skill_before_hash": request["skill_before_hash"],
                     "failure_case_ids": [event["case_id"]], "evidence_refs": [{"event_id": event["event_id"],
                     "artifact_hash": event["artifact_hash"], "quote": "only inspected first five rows"}],
                     "diagnosis": "missing_check", "repair_operator": "ADD_CHECK", "target_rule_id": "document_end",
                     "patch": edit, "expected_observation": "Checks all cells", "preserve_cases": []}
            else:
                p = edit
            return canonical({"status": "proposals", "reason": "observed incomplete scan", "proposals": [p]}), {"prompt_tokens": 10, "completion_tokens": 20}
        monkeypatch.setattr(engine, "chat_optimizer", chat)
        adapter = Adapter(selection)
        return cfg, adapter, prompts
    return create


def _identity(tmp_path):
    import sqlite3
    with sqlite3.connect(tmp_path / "run/remem/ledger.sqlite3") as db:
        return db.execute("SELECT payload FROM records WHERE id='run_identity'").fetchone()[0]


def _store(cfg):
    root = Path(cfg["out_root"]).parent
    return EventStore(Path(cfg["out_root"]) / "remem", json.loads(_identity(root)))


@pytest.mark.parametrize("kind", ["skillopt_controlled", "cam_reference"])
def test_native_controls_preserve_history_and_resume(make_run, monkeypatch, kind):
    from skillopt.remem import native_control
    cfg, adapter, _ = make_run()
    schedule = cfg.pop("remem")["task_schedule"]
    cfg.update(control_kind=kind, control_task_schedule=schedule)
    contexts = []
    def reflect(results, skill, directory, **kwargs):
        contexts.append(kwargs.get("step_buffer_context", ""))
        assert _store(cfg).records("observation")
        content = "CHECK" if "CHECK" not in skill else "PRESERVE"
        return [{"source_type": "failure", "patch": {"edits": [{"op": "append", "content": content,
                     "support_task_ids": ["t1"], "support_count": 1}]}}]
    adapter.reflect = reflect
    monkeypatch.setattr(native_control, "merge_patches", lambda skill, failure, success, **kw:
                        {"edits": [e for patch in failure + success for e in patch["edits"]]})
    monkeypatch.setattr(native_control, "rank_and_select", lambda skill, patch, **kw: patch)
    result = engine.ReflACTTrainer(cfg, adapter).train()
    assert result["total_steps"] == 2 and result["control"]["gates"] >= 1
    assert contexts[1].strip()  # Original native history is not suppressed as in core_00.
    before = len(adapter.calls), len(contexts)
    resumed = engine.ReflACTTrainer(cfg, adapter).train()
    assert resumed["total_steps"] == 2
    assert (len(adapter.calls), len(contexts)) == before


@pytest.mark.parametrize("repair,memory", [(False, False), (True, False), (False, True), (True, True)])
def test_actual_trainer_four_arms_and_no_history_leak(make_run, repair, memory):
    cfg, adapter, prompts = make_run(repair, memory, replies="no_change")
    summary = engine.ReflACTTrainer(cfg, adapter).train()
    store = _store(cfg)
    assert summary["total_steps"] == 2
    assert len(store.records("observation")) == 2
    assert len(store.records("attempt")) == 2
    assert prompts[0]["history"] == []
    assert bool(prompts[1]["history"]) is memory
    assert ("rules" in prompts[0]) is repair
    assert "v0" not in canonical(prompts)
    assert all(a["gate_action"] == "no_change" for a in store.records("attempt"))
    assert all(c.status == "unresolved" for c in store.cases(digest(Path(cfg["skill_init"]).read_text()), before_step=3))


@pytest.mark.parametrize("selection,action", [("improve", "accept"), ("tie", "inconclusive")])
def test_candidate_gate_and_completed_resume(make_run, selection, action):
    cfg, adapter, prompts = make_run(selection=selection, steps=1)
    engine.ReflACTTrainer(cfg, adapter).train()
    attempt = _store(cfg).records("attempt")[0]
    assert attempt["gate_action"] == action
    assert attempt["adopted"] == (action == "accept")
    assert attempt["attribution"] == "update_bundle"
    calls = len(adapter.calls)
    engine.ReflACTTrainer(cfg, adapter).train()
    assert len(adapter.calls) == calls
    assert len(prompts) == 1


@pytest.mark.parametrize("replies", ["invalid", "empty", "service_error"])
def test_generation_failure_keeps_training_observations(make_run, replies):
    cfg, adapter, prompts = make_run(replies=replies, steps=1)
    if replies == "invalid":
        engine.ReflACTTrainer(cfg, adapter).train()
        assert _store(cfg).records("attempt")[0]["gate_action"] == "proposal_invalid"
    else:
        with pytest.raises(InfrastructureFailure):
            engine.ReflACTTrainer(cfg, adapter).train()
    assert len(_store(cfg).records("observation")) == 1


def test_interrupted_rollout_cannot_silently_repeat(make_run):
    cfg, adapter, prompts = make_run(steps=1)
    adapter.interrupt = True
    with pytest.raises(RuntimeError, match="interruption"):
        engine.ReflACTTrainer(cfg, adapter).train()
    calls = len(adapter.calls)
    adapter.interrupt = False
    with pytest.raises(InfrastructureFailure, match="reconciliation"):
        engine.ReflACTTrainer(cfg, adapter).train()
    assert len(adapter.calls) == calls
    assert not prompts


def test_checkpoint_recovers_without_trusting_partial_json_files(make_run):
    cfg, adapter, prompts = make_run(replies="no_change", steps=1)
    engine.ReflACTTrainer(cfg, adapter).train()
    directory = Path(cfg["out_root"])
    for name in ("history.json", "runtime_state.json", "best_skill.md"):
        (directory / name).write_text("partial/crashed write", encoding="utf-8")
    calls = len(adapter.calls)
    result = engine.ReflACTTrainer(cfg, adapter).train()
    assert result["total_steps"] == 1 and len(adapter.calls) == calls
    assert (directory / "best_skill.md").read_text() == Path(cfg["skill_init"]).read_text()


def test_mixed_infrastructure_and_task_failures_preserve_valid_failures(make_run):
    cfg, adapter, prompts = make_run(steps=1)
    adapter.loader.train_items = [{"id": "t1", "instruction": "synthetic"}, {"id": "t2", "instruction": "synthetic"}]
    cfg.update(batch_size=2, train_size=2)
    cfg["remem"]["task_schedule"] = [["t1", "t2"]]
    original = adapter.rollout
    def mixed(env, *args, **kwargs):
        rows = original(env, *args, **kwargs)
        for row in rows:
            if row["id"] == "t2":
                row.update(llm_ok=False, fail_reason="llm-call-failed: synthetic")
        return rows
    adapter.rollout = mixed
    with pytest.raises(InfrastructureFailure):
        engine.ReflACTTrainer(cfg, adapter).train()
    assert len(_store(cfg).records("observation")) == 1
    assert not prompts


def test_real_spreadsheet_adapter_executor_and_trainer_without_model_calls(make_run, monkeypatch):
    from openpyxl import Workbook

    from skillopt.envs.spreadsheetbench import codegen_agent
    from skillopt.envs.spreadsheetbench.adapter import SpreadsheetBenchAdapter

    cfg, _, prompts = make_run(replies="no_change", steps=1)
    root = Path(cfg["out_root"]).parent
    payload, splits = root / "synthetic_data", root / "splits"
    for split, task in (("train", "t1"), ("val", "v1"), ("test", "private_test")):
        folder = payload / task
        folder.mkdir(parents=True)
        workbook = Workbook()
        workbook.active["A1"] = 2
        workbook.save(folder / "initial.xlsx")
        workbook.active["A1"] = 4
        workbook.save(folder / "golden.xlsx")
        workbook.close()
        (splits / split).mkdir(parents=True)
        (splits / split / "items.json").write_text(json.dumps([{
            "id": task, "instruction": "Double A1", "instruction_type": "Cell-Level Manipulation",
            "answer_position": "Sheet!A1", "answer_sheet": "Sheet", "spreadsheet_path": task,
        }]), encoding="utf-8")
    code = "import openpyxl\nw = openpyxl.load_workbook(INPUT_PATH)\nw.save(OUTPUT_PATH)\nw.close()"
    def single(**kwargs):
        assert "private_test" not in str(kwargs)
        return {"code": code, "raw": code, "n_turns": 1, "conversation": [{"role": "assistant", "content": code}]}
    monkeypatch.setattr(codegen_agent, "run_single", single)
    cfg.update(env="spreadsheetbench", split_mode="split_dir", split_dir=str(splits), data_root=str(payload), sel_env_num=1)
    adapter = SpreadsheetBenchAdapter(split_mode="split_dir", split_dir=str(splits), data_root=str(payload), workers=1)
    result = engine.ReflACTTrainer(cfg, adapter).train()
    assert result["remem"]["observations"] == 1
    assert result["remem"]["task_executions"] == 2
    assert "code.py" in prompts[0]["current_training_observations"][0]["trace"]
    assert "private_test" not in canonical(prompts)
