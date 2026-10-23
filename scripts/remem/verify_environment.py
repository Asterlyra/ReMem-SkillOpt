"""Verify imports, prepared data and synthetic spreadsheet execution offline."""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def verify() -> dict:
    packages = {
        "openai": "openai", "pyyaml": "yaml", "numpy": "numpy",
        "openpyxl": "openpyxl", "azure-identity": "azure.identity",
        "azure-core": "azure.core", "httpx": "httpx", "pandas": "pandas",
        "json-repair": "json_repair", "pytest": "pytest",
    }
    versions = {}
    for distribution, module in packages.items():
        importlib.import_module(module)
        versions[distribution] = importlib.metadata.version(distribution)
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True, capture_output=True)
    from openpyxl import Workbook

    from skillopt.envs.spreadsheetbench.evaluator import compare_workbooks
    from skillopt.envs.spreadsheetbench.executor import run_generated_code
    from skillopt.envs.spreadsheetbench.rollout import _find_test_cases

    with tempfile.TemporaryDirectory(prefix="remem-offline-") as scratch:
        directory = Path(scratch)
        source, gold, output = [directory / name for name in ("input.xlsx", "gold.xlsx", "output.xlsx")]
        workbook = Workbook()
        workbook.active["A1"] = 2
        workbook.save(source)
        workbook.active["A1"] = 4
        workbook.save(gold)
        workbook.close()
        code = "import openpyxl\nw = openpyxl.load_workbook(INPUT_PATH)\nw.active['A1'].value *= 2\nw.save(OUTPUT_PATH)\nw.close()"
        ok, reason = run_generated_code(code, str(source), str(output), timeout=30)
        if not ok:
            raise RuntimeError(f"Synthetic executor failed: {reason}")
        ok, reason = compare_workbooks(str(gold), str(output), "Sheet!A1")
        if not ok:
            raise RuntimeError(f"Synthetic evaluator failed: {reason}")
    manifest = json.loads((ROOT / "data/remem_data_manifest.json").read_text(encoding="utf-8"))
    data_root = ROOT / manifest["runtime_data_root"]
    counts = {}
    for split in ("train", "val", "test"):
        rows = json.loads((ROOT / "data/spreadsheetbench_split" / split / "items.json").read_text(encoding="utf-8"))
        for row in rows:
            if not _find_test_cases(str(data_root / row["spreadsheet_path"])):
                raise ValueError("Task not loadable by the production case finder")
        counts[split] = len(rows)
    return {"status": "passed", "python": platform.python_version(), "platform": platform.system(),
            "packages": versions, "loadable_splits": counts, "synthetic_executor_evaluator": "passed",
            "model_calls": 0, "formal_experiment_ready": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
