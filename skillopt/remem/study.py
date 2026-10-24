"""Preparation, immutable source bundles, verification, execution and reporting.

This foundation runs core arms in development mode. Formal study promotion is
deliberately unavailable until model, exposure and external-control audits exist.
"""
from __future__ import annotations

import copy
import importlib.metadata
import json
import platform
import random
import re
import sqlite3
import subprocess
import sys
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


def prepare(study_id: str, *, root: Path = ROOT) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", study_id):
        raise ValueError("Invalid study ID")
    directory = root / "outputs/remem" / study_id
    if directory.exists():
        raise FileExistsError("Study already exists; choose a new version")
    data_path = root / "data/remem_data_manifest.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    train = json.loads((root / "data/spreadsheetbench_split/train/items.json").read_text(encoding="utf-8"))
    selection = json.loads((root / "data/spreadsheetbench_split/val/items.json").read_text(encoding="utf-8"))
    if len(train) != 80 or len(selection) != 40:
        raise ValueError("Unexpected development split sizes")
    if {str(r["id"]) for r in train} & {str(r["id"]) for r in selection}:
        raise ValueError("Overlapping train and selection IDs")
    base = flatten_config(load_config(str(root / "configs/remem/core.yaml")))
    directory.mkdir(parents=True)
    config_hashes = {}
    order = []
    for seed in (42, 43, 44):
        schedule = task_plan(train, seed)
        arms = list(CORE_ARMS)
        random.Random(seed + 10000).shuffle(arms)
        for arm in arms:
            repair, memory = CORE_ARMS[arm]
            name = f"{arm}_{seed}"
            cfg = copy.deepcopy(base)
            cfg.update(seed=seed, out_root=str(directory / "runs" / name))
            for key in ("skill_init", "data_root", "split_dir"):
                cfg[key] = str((root / cfg[key]).resolve())
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
        "schema_version": 1, "study_id": study_id, "scope": "development_core_only", "formal_ready": False,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()),
        "source": snapshot, "configs": config_hashes, "environment": environment(),
        "data_manifest_hash": file_hash(data_path), "data_root": data["runtime_data_root"],
        "data_files": data["runtime_files"], "run_order": order,
        "split_hashes": {s: file_hash(root / "data/spreadsheetbench_split" / s / "items.json") for s in ("train", "val", "test")},
        "formal_blockers": ["model_identity_cost_throughput_preflight", "historical_test_exposure_audit",
                            "source_template_group_audit", "transport_attempt_usage_accounting",
                            "external_control_implementations", "final_test_release_protocol"],
        "external_arms": {k: "planned" for k in ("skillopt_controlled", "cam_reference", "atomsearch_budgeted")},
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
        ReMemConfig.parse(json.loads((directory / path).read_text(encoding="utf-8")))
    if environment() != freeze["environment"]:
        raise ValueError("Python environment differs from frozen versions")
    if file_hash(root / "data/remem_data_manifest.json") != freeze["data_manifest_hash"]:
        raise ValueError("Data manifest changed")
    runtime_root = root / freeze["data_root"]
    if {p.relative_to(runtime_root).as_posix() for p in runtime_root.rglob("*") if p.is_file()} != set(freeze["data_files"]):
        raise ValueError("Data file inventory changed after freeze")
    for path, expected in freeze["data_files"].items():
        if file_hash(root / freeze["data_root"] / path) != expected:
            raise ValueError("Data payload changed")
    for split, expected in freeze["split_hashes"].items():
        if file_hash(root / "data/spreadsheetbench_split" / split / "items.json") != expected:
            raise ValueError("Task split changed")
    return {"status": "passed", "scope": freeze["scope"], "formal_ready": False,
            "core_runs": len(freeze["run_order"]), "formal_blockers": freeze["formal_blockers"]}


def run(directory: Path, name: str, *, execute: bool = False) -> dict:
    verification = verify(directory)
    freeze = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    if name not in freeze["run_order"]:
        raise ValueError("Run not in frozen development matrix")
    cfg = json.loads((directory / "configs" / f"{name}.json").read_text(encoding="utf-8"))
    if not execute:
        return {"status": "not_started", "run": name, "verification": verification, "model_calls": 0}
    if not sys.flags.utf8_mode:
        raise ValueError("Use scripts/remem/python.ps1 or Python -X utf8 for development execution")
    # Explicit --execute starts real development calls; never a formal claim.
    from scripts.train import get_adapter
    from skillopt.engine.trainer import ReflACTTrainer

    return ReflACTTrainer(cfg, get_adapter(cfg)).train()


def report(directory: Path) -> dict:
    """Read existing artifacts only; no store construction or model imports."""
    freeze = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    rows = []
    for name in freeze["run_order"]:
        folder = directory / "runs" / name
        summary_path, ledger = folder / "summary.json", folder / "remem/ledger.sqlite3"
        row = {"run": name, "status": "not_started", "task_executions": None, "http_attempts": None, "tokens": None}
        if ledger.exists():
            uri = ledger.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True) as db:
                records = [(kind, json.loads(body)) for kind, body in db.execute("SELECT kind,payload FROM records")]
            row["status"] = "incomplete"
            row["task_executions"] = sum(p["tasks"] for k, p in records if k == "rollout_started")
            row["task_failures"] = sum(k == "observation" and p["outcome"] == "failure" for k, p in records)
            row["infra_failures"] = sum(k in {"infra_failure", "optimizer_error"} for k, p in records)
            row["no_change"] = sum(k == "attempt" and p["gate_action"] == "no_change" for k, p in records)
            row["proposal_invalid"] = sum(k == "proposal_invalid" or (k == "proposal_result" and p["status"] == "proposal_invalid") for k, p in records)
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            row.update(status="development_completed", selection_score=summary["best_selection_hard"],
                       steps=summary["total_steps"], elapsed_s=summary["total_wall_time_s"])
        rows.append(row)
    return {"scope": freeze["scope"], "formal_ready": False, "runs": rows, "external_arms": freeze["external_arms"]}
