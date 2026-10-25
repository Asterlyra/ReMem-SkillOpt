"""Preparation, immutable source bundles, verification, execution and reporting.

This foundation runs core arms in development mode. Formal study promotion is
deliberately unavailable until model, exposure and external-control audits exist.
"""
from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import platform
import random
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

from skillopt.config import flatten_config, load_config

from .config import ReMemConfig

ROOT = Path(__file__).resolve().parents[2]
CORE_ARMS = {"core_00": (False, False), "repair_only": (True, False),
             "memory_only": (False, True), "remem_full": (True, True)}


def file_hash(path: Path) -> str:
    import hashlib
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def environment() -> dict:
    return {"python": platform.python_version(), "platform": platform.system(),
            "utf8_mode": sys.flags.utf8_mode,
            "packages": {d.metadata["Name"].lower(): d.version for d in importlib.metadata.distributions()}}


def task_plan(items: list[dict], seed: int, batch_size: int = 20, revisit: int = 40) -> list[list[str]]:
    if len(items) % batch_size or revisit % batch_size or not 0 < revisit <= len(items):
        raise ValueError("Task pool/revisit must fit complete batches")
    groups: dict[str, list[str]] = {}
    for item in items:
        groups.setdefault(str(item["instruction_type"]), []).append(str(item["id"]))
    rng = random.Random(seed)
    for group in groups.values():
        group.sort()
        rng.shuffle(group)
    # Allocate each task type by largest remainder, without observing outcomes.
    quotas = {k: len(v) * revisit // len(items) for k, v in groups.items()}
    for k in sorted(groups, key=lambda k: (-(len(groups[k])*revisit % len(items)), k))[:revisit-sum(quotas.values())]:
        quotas[k] += 1
    recurring = [task for k in sorted(groups) for task in groups[k][:quotas[k]]]
    # Proportional interleaving distributes task types through the first pass.
    first = [task for _, _, task in sorted((i/len(v), k, task) for k, v in groups.items() for i, task in enumerate(v))]
    rng.shuffle(recurring)
    return [first[i:i+batch_size] for i in range(0, len(first), batch_size)] + [recurring[i:i+batch_size] for i in range(0, revisit, batch_size)]


def source_files(root: Path) -> list[Path]:
    files = set()
    for name in ("skillopt", "scripts", "configs", "tests", "docs/remem", "research/remem"):
        for path in (root / name).rglob("*"):
            if (path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml", ".json", ".txt", ".ps1", ".sh", ".toml"}
                    and "__pycache__" not in path.parts and "local" not in path.parts
                    and ".local." not in path.name and ".secret." not in path.name):
                if path.is_symlink():
                    raise ValueError("Source snapshot must not follow symlinks")
                files.add(path)
    files.update(root / p for p in ("pyproject.toml", "requirements.txt", "requirements-remem.txt", "AGENTS.md", "START_HERE.md", "HANDOFF.md"))
    return sorted(files)


def prepare(study_id: str, *, root: Path = ROOT, config_path: Path | None = None,
            data_manifest_path: Path | None = None, include_skillopt_controlled: bool = False,
            include_cam_reference: bool = False, include_atomsearch: bool = False,
            calibration: bool = False) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", study_id):
        raise ValueError("Invalid study ID")
    directory = root / "outputs/remem" / study_id
    if directory.exists():
        raise FileExistsError("Study already exists; choose a new version")
    config_source = (config_path or root / "configs/remem/core.yaml").resolve()
    data_path = (data_manifest_path or root / "data/remem_data_manifest.json").resolve()
    if not config_source.is_relative_to(root.resolve()) or not data_path.is_relative_to(root.resolve()):
        raise ValueError("Study inputs must be inside the repository")
    base = flatten_config(load_config(str(config_source)))
    data = json.loads(data_path.read_text(encoding="utf-8"))
    split_root = (root / base["split_dir"]).resolve()
    train = json.loads((split_root / "train/items.json").read_text(encoding="utf-8"))
    selection = json.loads((split_root / "val/items.json").read_text(encoding="utf-8"))
    test = json.loads((split_root / "test/items.json").read_text(encoding="utf-8"))
    if len(train) != 80 or len(selection) != 40:
        raise ValueError("Unexpected development split sizes")
    identities = [{str(r["id"]) for r in rows} for rows in (train, selection, test)]
    if any(len(identity) != len(rows) for identity, rows in zip(identities, (train, selection, test))) or any(
            identities[i] & identities[j] for i, j in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("Duplicate or overlapping train, selection, and test IDs")
    if base["data_root"] != data["runtime_data_root"] or "runtime_files" not in data:
        raise ValueError("Study config and data manifest differ")
    directory.mkdir(parents=True)
    if calibration:
        def subset(rows, count, seed):
            groups = {}
            for row in sorted(rows, key=lambda r: str(r["id"])):
                groups.setdefault(row.get("instruction_type", "unknown"), []).append(row)
            rng = random.Random(seed)
            for group in groups.values():
                rng.shuffle(group)
            return [row for _, _, row in sorted((i/len(g), k, r) for k, g in groups.items() for i, r in enumerate(g))][:count]
        train, selection = subset(train, 6, 20261024), subset(selection, 4, 20261025)
        split_root = directory / "calibration_split"
        for split, rows in (("train", train), ("val", selection), ("test", [])):
            write_json(split_root / split / "items.json", rows)
        base.update(train_size=6, batch_size=6, sel_env_num=4, test_env_num=0, split_dir=str(split_root))
        base["remem"].update(task_executions=32, optimizer_calls=20)
    config_hashes = {}
    order = []
    for seed in ((42,) if calibration else (42, 43, 44)):
        schedule = ([[str(r["id"]) for r in train]] * 2 if calibration else task_plan(train, seed))
        arms = ["remem_full"] if calibration else list(CORE_ARMS)
        if include_skillopt_controlled:
            arms.append("skillopt_controlled")
        if include_cam_reference:
            arms.append("cam_reference")
        if include_atomsearch:
            arms.append("atomsearch_budgeted")
        random.Random(seed + 10000).shuffle(arms)
        for arm in arms:
            name = f"{arm}_{seed}"
            cfg = copy.deepcopy(base)
            cfg.update(seed=seed, out_root=str(directory / "runs" / name))
            for key in ("skill_init", "data_root", "split_dir"):
                cfg[key] = str((root / cfg[key]).resolve())
            cfg["research_limits"] = dict(task_executions=400, optimizer_calls=80, output_tokens=16384,
                                          max_attempts=3, timeout_s=120, target_calls=400)
            if calibration:
                cfg["research_limits"].update(task_executions=32, target_calls=32, optimizer_calls=20)
            if arm not in CORE_ARMS:
                cfg.pop("remem")
                cfg.update(train_size=len(train), control_task_schedule=schedule, control_kind=arm)
                if arm == "atomsearch_budgeted":
                    from .atomsearch import DEFAULTS
                    cfg["atomsearch"] = {**DEFAULTS, **({"attempts": 2} if calibration else {})}
                if arm == "cam_reference":
                    from .native_control import CAM_V3
                    cfg["cam_control"] = dict(CAM_V3)
            else:
                repair, memory = CORE_ARMS[arm]
                cfg["remem"].update(repair=repair, memory=memory, run_id=f"{study_id}:{name}", task_schedule=schedule)
                ReMemConfig.parse(cfg)
            config_path = directory / "configs" / f"{name}.json"
            write_json(config_path, cfg)
            config_hashes[config_path.relative_to(directory).as_posix()] = file_hash(config_path)
            order.append(name)
    snapshot = {}
    for path in source_files(root):
        relative = path.relative_to(root)
        dest = directory / "source" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        snapshot[relative.as_posix()] = file_hash(dest)
    manifest = {
        "schema_version": 1, "study_id": study_id,
        "scope": "calibration_only" if calibration else "development_with_external_controls" if any((include_skillopt_controlled, include_cam_reference, include_atomsearch)) else "development_core_only",
        "formal_ready": False,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()),
        "source": snapshot, "configs": config_hashes, "environment": environment(),
        "config_template": config_source.relative_to(root).as_posix(),
        "data_manifest_path": data_path.relative_to(root).as_posix(),
        "data_manifest_hash": file_hash(data_path), "data_root": data["runtime_data_root"],
        "data_files": data["runtime_files"], "run_order": order,
        "split_dir": split_root.relative_to(root).as_posix(),
        "split_hashes": {s: file_hash(split_root / s / "items.json") for s in ("train", "val", "test")},
        "formal_blockers": ["model_identity_cost_throughput_calibration",
                            "fresh_test_source_template_and_quality_audit",
                            "failed_request_usage_reconciliation",
                            "external_control_live_validation", "final_test_release_protocol"],
        "external_arms": {"skillopt_controlled": "implemented_development" if include_skillopt_controlled else "planned",
                          "cam_reference": "implemented_development" if include_cam_reference else "not_included",
                          "atomsearch_budgeted": "independent_reproduction_development" if include_atomsearch else "not_included"},
    }
    write_json(directory / "freeze.json", manifest)
    (directory / "freeze.sha256").write_text(file_hash(directory / "freeze.json") + "\n", encoding="ascii")
    return directory


def verify(directory: Path, *, root: Path = ROOT) -> dict:
    if file_hash(directory / "freeze.json") != (directory / "freeze.sha256").read_text().strip():
        raise ValueError("Freeze manifest changed")
    freeze = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    if {p.relative_to(root).as_posix() for p in source_files(root)} != set(freeze["source"]):
        raise ValueError("Source file inventory changed after freeze")
    for path, expected in freeze["source"].items():
        if file_hash(root / path) != expected or file_hash(directory / "source" / path) != expected:
            raise ValueError(f"Source changed after freeze: {path}")
    for path, expected in freeze["configs"].items():
        if file_hash(directory / path) != expected:
            raise ValueError("Frozen config changed")
        config = json.loads((directory / path).read_text(encoding="utf-8"))
        if config.get("control_kind") in {"skillopt_controlled", "cam_reference", "atomsearch_budgeted"}:
            if len(config.get("control_task_schedule", [])) != (2 if freeze["scope"] == "calibration_only" else 6) or config.get("eval_test"):
                raise ValueError("Invalid SkillOpt control config")
        else:
            ReMemConfig.parse(config)
    if environment() != freeze["environment"]:
        raise ValueError("Python environment differs from frozen versions")
    if file_hash(root / freeze.get("data_manifest_path", "data/remem_data_manifest.json")) != freeze["data_manifest_hash"]:
        raise ValueError("Data manifest changed")
    runtime_root = root / freeze["data_root"]
    if {p.relative_to(runtime_root).as_posix() for p in runtime_root.rglob("*") if p.is_file()} != set(freeze["data_files"]):
        raise ValueError("Data file inventory changed after freeze")
    for path, expected in freeze["data_files"].items():
        if file_hash(root / freeze["data_root"] / path) != expected:
            raise ValueError("Data payload changed")
    for split, expected in freeze["split_hashes"].items():
        if file_hash(root / freeze.get("split_dir", "data/spreadsheetbench_split") / split / "items.json") != expected:
            raise ValueError("Task split changed")
    return {"status": "passed", "scope": freeze["scope"], "formal_ready": False,
            "core_runs": sum(any(name.startswith(arm + "_") for arm in CORE_ARMS) for name in freeze["run_order"]),
            "external_runs": sum(not any(name.startswith(arm + "_") for arm in CORE_ARMS) for name in freeze["run_order"]),
            "formal_blockers": freeze["formal_blockers"]}


def run(directory: Path, name: str, *, execute: bool = False, key_file: Path | None = None) -> dict:
    verification = verify(directory)
    freeze = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    if name not in freeze["run_order"]:
        raise ValueError("Run not in frozen development matrix")
    cfg = json.loads((directory / "configs" / f"{name}.json").read_text(encoding="utf-8"))
    if not execute:
        return {"status": "not_started", "run": name, "verification": verification, "model_calls": 0}
    return execute_config(cfg, key_file=key_file)


def execute_config(cfg: dict, *, key_file: Path | None = None) -> dict:
    """Execute a caller-verified development config under shared call limits."""
    if not sys.flags.utf8_mode:
        raise ValueError("Use scripts/remem/python.ps1 or Python -X utf8 for development execution")
    # Explicit --execute starts real development calls; never a formal claim.
    from scripts.train import get_adapter
    from skillopt.engine.trainer import ReflACTTrainer
    env_keys = ("OPTIMIZER_AZURE_OPENAI_API_KEY", "TARGET_AZURE_OPENAI_API_KEY", "REMEM_TRANSPORT_AUDIT_PATH")
    previous = {key: os.environ.get(key) for key in env_keys}
    from skillopt.model import azure_openai as backend
    previous_backend_keys = backend.OPTIMIZER_API_KEY, backend.TARGET_API_KEY
    try:
        if key_file is not None:
            key_file = key_file.resolve()
            if not key_file.is_relative_to(ROOT) or subprocess.run(
                    ["git", "check-ignore", "-q", "--", str(key_file)], cwd=ROOT, check=False).returncode != 0:
                raise ValueError("DeepSeek key file must be Git-ignored inside this repository")
            if (cfg.get("optimizer_model") != "deepseek-flash" or cfg.get("target_model") != "deepseek-flash"
                    or cfg.get("optimizer_azure_openai_endpoint") != "https://api.deepseek.com"
                    or cfg.get("target_azure_openai_endpoint") != "https://api.deepseek.com"):
                raise ValueError("Local DeepSeek key file requires the pinned DeepSeek profile")
            entries = dict(line.split("=", 1) for line in key_file.read_text(encoding="utf-8").splitlines()
                           if line and not line.startswith("#") and "=" in line)
            key = entries.get("DEEPSEEK_API_KEY", "")
            if not key:
                raise ValueError("Local DeepSeek API key missing")
            os.environ["OPTIMIZER_AZURE_OPENAI_API_KEY"] = key
            os.environ["TARGET_AZURE_OPENAI_API_KEY"] = key
        os.environ["REMEM_TRANSPORT_AUDIT_PATH"] = str((Path(cfg["out_root"]) / "remem/transport.jsonl").resolve())
        # Model modules were imported before loading the ignored key file. Refresh
        # their in-memory credentials explicitly without placing secrets in cfg.
        backend.configure_azure_openai(optimizer_api_key=os.environ.get(env_keys[0]),
                                       target_api_key=os.environ.get(env_keys[1]))
        adapter = get_adapter(cfg)
        from .call_policy import ResearchCallPolicy, use_call_policy
        limits = dict(cfg.get("research_limits", {}))
        limits.pop("task_executions", None)
        policy = ResearchCallPolicy(Path(cfg["out_root"]), **limits)
        invocation, started, error_type = uuid.uuid4().hex, time.monotonic(), None
        policy.store.append(invocation, "execution_started", {"invocation": invocation})
        try:
            with use_call_policy(policy):
                return ReflACTTrainer(cfg, adapter).train()
        except BaseException as exc:
            error_type = type(exc).__name__
            raise
        finally:
            policy.store.append(invocation + ":finished", "execution_finished", {"invocation": invocation,
                "elapsed_s": time.monotonic() - started, "error_type": error_type,
                "scope": "trainer_including_setup_baseline_optimization_summary"})
    finally:
        backend.OPTIMIZER_API_KEY, backend.TARGET_API_KEY = previous_backend_keys
        for client_name in ("_optimizer_client", "_target_client"):
            client = getattr(backend, client_name)
            if client is not None:
                client.close()
            setattr(backend, client_name, None)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def report(directory: Path) -> dict:
    """Read existing artifacts only; no store construction or model imports."""
    freeze = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    rows = []
    for name in freeze["run_order"]:
        folder = directory / "runs" / name
        summary_path, ledger = folder / "summary.json", folder / "remem/ledger.sqlite3"
        row = {"run": name, "status": "not_started", "task_executions": None,
               "http_attempts": None, "retry_attempts": None, "cache_hits": None, "tokens": None}
        audit_file = folder / "remem/transport.jsonl"
        if audit_file.exists():
            from .transport_audit import summarize
            audit = summarize(audit_file)
            row["http_attempts"] = audit["http_attempts"]
            row["retry_attempts"] = audit["retry_attempts"]
            row["http_elapsed_s_sum"] = audit["http_elapsed_s_sum"]
            row["logical_timing_complete"] = audit["logical_timing_complete"]
            row["logical_call_elapsed_s_sum"] = audit["logical_call_elapsed_s_sum"]
            row["tokens"] = ({"prompt": audit["prompt_tokens"], "completion": audit["completion_tokens"],
                              "cached_prompt": audit["cached_prompt_tokens"]} if audit["usage_complete"] else None)
            row["usage_complete"] = audit["usage_complete"]
        if ledger.exists():
            uri = ledger.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True) as db:
                records = [(kind, json.loads(body)) for kind, body in db.execute("SELECT kind,payload FROM records")]
            row["status"] = "incomplete"
            row["task_executions"] = sum(p["tasks"] for k, p in records if k == "rollout_started")
            row["cache_hits"] = sum(k == "cache_hit" for k, _ in records)
            row["task_failures"] = sum(k == "observation" and p["outcome"] == "failure" for k, p in records)
            row["infra_failures"] = sum(k in {"infra_failure", "optimizer_error"} for k, p in records)
            row["no_change"] = sum(k == "attempt" and p["gate_action"] == "no_change" for k, p in records)
            row["proposal_invalid"] = sum(k == "proposal_invalid" or (k == "proposal_result" and p["status"] == "proposal_invalid") for k, p in records)
        calls = folder / "remem/calls/ledger.sqlite3"
        if calls.exists():
            with sqlite3.connect(calls.resolve().as_uri() + "?mode=ro", uri=True) as db:
                records = [(kind, json.loads(body)) for kind, body in db.execute("SELECT kind,payload FROM records")]
            starts = [p for k, p in records if k == "execution_started"]
            finishes = [p for k, p in records if k == "execution_finished"]
            timing_complete = bool(starts) and {r["invocation"] for r in starts} == {r["invocation"] for r in finishes}
            row["execution_timing_complete"] = timing_complete
            row["execution_wall_time_s"] = sum(r["elapsed_s"] for r in finishes) if timing_complete else None
            row["optimizer_logical_calls"] = sum(k == "start" for k, _ in records)
        control_journal = folder / "remem/control_rollouts.jsonl"
        if control_journal.exists():
            entries = [json.loads(line) for line in control_journal.read_text(encoding="utf-8").splitlines() if line]
            row["status"] = "incomplete"
            row["task_executions"] = sum(entry["tasks"] for entry in entries if entry["kind"] == "start")
            row["cache_hits"] = sum(entry["kind"] == "cache" for entry in entries)
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            row.update(status="development_completed", selection_score=summary["best_selection_hard"],
                       steps=summary["total_steps"], elapsed_s=summary["total_wall_time_s"],
                       stop_reason=summary.get("status"), final_selection_score=summary.get("final_selection_hard"))
        rows.append(row)
    return {"scope": freeze["scope"], "formal_ready": False, "runs": rows, "external_arms": freeze["external_arms"]}
