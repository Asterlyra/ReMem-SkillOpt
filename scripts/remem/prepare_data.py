"""Materialize the pinned SpreadsheetBench payload without any model calls.

The upstream 280-task test pool is NOT a newly audited ReMem final test set.
Raw payloads, instructions, answers and manifests stay in ignored data/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

REVISION = "ab0b742b0fc95b946f212d80ac7771b5531272e4"
ARCHIVE_NAME = "spreadsheetbench_verified_400.tar.gz"
ARCHIVE_SHA256 = "10ef893dd29cb13ab97143ea787e68cdc9574a13873ab9a54e50b31dc03fc949"
PAYLOAD_NAME = "spreadsheetbench_verified_400"
SOURCE = f"https://huggingface.co/datasets/KAKA22/SpreadsheetBench/resolve/{REVISION}/{ARCHIVE_NAME}"
ROOT = Path(__file__).resolve().parents[2]
RUNTIME_NAME = "spreadsheetbench_remem_400"
# The pinned release misspells the task ID in this golden workbook filename.
# Preserve the original archive and make a byte-identical alias in a derived copy.
FILE_ALIASES = {
    "spreadsheet/42930/1_43930_golden.xlsx": "spreadsheet/42930/1_42930_golden.xlsx",
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json_once(path: Path, value: object) -> None:
    """An existing different artifact is an error, never silently overwritten."""
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != body:
            raise ValueError(f"Existing artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(body)


def extract_verified(archive: Path, data_dir: Path) -> Path:
    if sha256(archive) != ARCHIVE_SHA256:
        raise ValueError("Archive SHA-256 does not match the pinned source")
    target = data_dir / PAYLOAD_NAME
    if target.exists():
        # Verify every member against the trusted archive before reusing it.
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if member.isfile():
                    source = bundle.extractfile(member)
                    path = data_dir / member.name
                    if source is None or not path.is_file():
                        raise ValueError(f"Missing payload member: {member.name}")
                    if hashlib.sha256(source.read()).hexdigest() != sha256(path):
                        raise ValueError(f"Modified payload member: {member.name}")
        return target
    with tempfile.TemporaryDirectory(prefix="remem-data-", dir=data_dir) as scratch:
        scratch_path = Path(scratch)
        with tarfile.open(archive) as bundle:
            for member in bundle:
                name = PurePosixPath(member.name)
                if (name.is_absolute() or ".." in name.parts or "\\" in member.name
                        or ":" in member.name or not name.parts
                        or name.parts[0] != PAYLOAD_NAME
                        or not (member.isfile() or member.isdir())):
                    raise ValueError("Unsafe archive member")
                destination = scratch_path.joinpath(*name.parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    if source is None:
                        raise ValueError("Unreadable archive member")
                    with destination.open("xb") as output:
                        shutil.copyfileobj(source, output)
        (scratch_path / PAYLOAD_NAME).rename(target)
    return target


def prepare(root: Path = ROOT, *, download: bool = True) -> dict:
    data_dir = root / "data"
    download_dir = data_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    archive = download_dir / ARCHIVE_NAME
    if not archive.exists():
        if not download:
            raise FileNotFoundError("Pinned archive is absent; run without --offline")
        with tempfile.NamedTemporaryFile(dir=download_dir, delete=False, suffix=".part") as output:
            temporary = Path(output.name)
            try:
                with urllib.request.urlopen(SOURCE, timeout=120) as response:
                    shutil.copyfileobj(response, output)
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        if sha256(temporary) != ARCHIVE_SHA256:
            temporary.unlink()
            raise ValueError("Downloaded archive SHA-256 mismatch")
        temporary.rename(archive)
    payload = extract_verified(archive, data_dir)
    runtime = data_dir / RUNTIME_NAME
    if not runtime.exists():
        with tempfile.TemporaryDirectory(prefix="remem-runtime-", dir=data_dir) as scratch:
            staging = Path(scratch) / RUNTIME_NAME
            shutil.copytree(payload, staging)
            for source, alias in FILE_ALIASES.items():
                shutil.copyfile(staging / source, staging / alias)
            staging.rename(runtime)
    for path in payload.rglob("*"):
        if path.is_file() and (not (runtime / path.relative_to(payload)).is_file()
                               or sha256(path) != sha256(runtime / path.relative_to(payload))):
            raise ValueError("Derived runtime payload differs from verified original")
    for source, alias in FILE_ALIASES.items():
        if not (runtime / alias).is_file() or sha256(payload / source) != sha256(runtime / alias):
            raise ValueError("Runtime filename alias is missing or differs from original bytes")
    rows = json.loads((payload / "dataset.json").read_text(encoding="utf-8"))
    by_id = {str(row["id"]): row for row in rows}
    if len(rows) != 400 or len(by_id) != 400:
        raise ValueError("Expected 400 unique tasks")
    from openpyxl import load_workbook

    workbook_files = sorted(payload.rglob("*.xlsx"))
    for path in workbook_files:
        workbook = load_workbook(path, read_only=True, data_only=True)
        workbook.close()
    all_ids: set[str] = set()
    splits = {}
    task_manifest = []
    for split, expected in (("train", 80), ("val", 40), ("test", 280)):
        hints = json.loads((data_dir / "spreadsheetbench_id_split" / split / "items.json").read_text(encoding="utf-8"))
        ids = [str(row["id"]) for row in hints]
        if len(ids) != expected or len(set(ids)) != expected or all_ids.intersection(ids):
            raise ValueError(f"Invalid or overlapping split: {split}")
        all_ids.update(ids)
        materialized = []
        for hint in hints:
            row = by_id[str(hint["id"])]
            if any(row[k] != hint[k] for k in ("spreadsheet_path", "instruction_type")):
                raise ValueError("Source task metadata differs from released ID manifest")
            for key in ("instruction", "answer_position", "spreadsheet_path"):
                if not row.get(key):
                    raise ValueError(f"Missing required task field: {key}")
            folder = (runtime / row["spreadsheet_path"]).resolve()
            if not folder.is_relative_to(runtime.resolve()):
                raise ValueError("Task payload path escapes data root")
            inputs = sorted(folder.glob("*_init.xlsx"))
            if not inputs and (folder / "initial.xlsx").is_file() and (folder / "golden.xlsx").is_file():
                inputs = [folder / "initial.xlsx"]
            if not inputs or any(not (folder / ("golden.xlsx" if p.name == "initial.xlsx" else p.name.replace("_init.xlsx", "_golden.xlsx"))).is_file() for p in inputs):
                raise ValueError("Task has missing input/golden workbook pairs")
            materialized.append(row)
            task_manifest.append({"id": str(row["id"]), "split": split,
                                  "instruction_type": row["instruction_type"], "cases": len(inputs)})
        write_json_once(data_dir / "spreadsheetbench_split" / split / "items.json", materialized)
        splits[split] = len(ids)
    manifest = {
        "schema_version": 1, "source": SOURCE, "revision": REVISION,
        "license": "CC-BY-SA-4.0", "archive_sha256": ARCHIVE_SHA256,
        "runtime_data_root": f"data/{RUNTIME_NAME}", "filename_aliases": FILE_ALIASES,
        "splits": splits, "workbooks": len(workbook_files), "tasks": task_manifest,
        "files": {p.relative_to(payload).as_posix(): sha256(p) for p in sorted(payload.rglob("*")) if p.is_file()},
        "runtime_files": {p.relative_to(runtime).as_posix(): sha256(p) for p in sorted(runtime.rglob("*")) if p.is_file()},
        "final_test_status": "upstream_pool_only_requires_historical_exposure_and_source_group_audit",
    }
    write_json_once(data_dir / "remem_data_manifest.json", manifest)
    return {k: manifest[k] for k in ("revision", "archive_sha256", "splits", "workbooks", "final_test_status")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Require an already downloaded archive")
    args = parser.parse_args()
    print(json.dumps(prepare(download=not args.offline), indent=2))


if __name__ == "__main__":
    main()
