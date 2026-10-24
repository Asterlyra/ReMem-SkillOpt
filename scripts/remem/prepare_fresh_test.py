"""Prepare an unexposed SpreadsheetBench v1 holdout from the pinned 912 release.

The candidate pool is selected using IDs and source payloads only. No old
scores are read, and no model is run on the selected test tasks here.
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import tarfile
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "data/downloads/spreadsheetbench_912_v0.1.tar.gz"
ARCHIVE_SHA256 = "9cf7228b54f1edcdd4b372eb736774adf29cb4f804c9920229bac6c154833399"
REVISION = "ab0b742b0fc95b946f212d80ac7771b5531272e4"
PREFIX = "all_data_912_v0.1"
SEED = 20261024


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_once(path: Path, value: object) -> None:
    body = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(body)


def main() -> None:
    if sha256(ARCHIVE) != ARCHIVE_SHA256:
        raise ValueError("Pinned 912-task archive SHA-256 mismatch")
    old_manifest = json.loads((ROOT / "data/remem_data_manifest.json").read_text(encoding="utf-8"))
    verified = {str(task["id"]) for task in old_manifest["tasks"]}
    source_split = ROOT / "data/spreadsheetbench_split"
    train = json.loads((source_split / "train/items.json").read_text(encoding="utf-8"))
    val = json.loads((source_split / "val/items.json").read_text(encoding="utf-8"))
    if len(train) != 80 or len(val) != 40:
        raise ValueError("Unexpected training or validation split")
    with tarfile.open(ARCHIVE) as bundle:
        member = bundle.extractfile(f"{PREFIX}/dataset.json")
        if member is None:
            raise ValueError("Dataset metadata missing")
        rows = json.load(member)
        by_id = {str(row["id"]): row for row in rows}
        if len(rows) != 912 or len(by_id) != 912 or len(set(by_id) & verified) != 400:
            raise ValueError("Unexpected source task IDs")
        members = {item.name: item for item in bundle.getmembers() if item.isfile()}
        old_seen: set[str] = set()
        scanned = 0
        for path in (Path("E:/Programs/CAM/CAM-SkillOpt") / "outputs").rglob("results.jsonl"):
            scanned += 1
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict) and "id" in record:
                        old_seen.add(str(record["id"]))
        candidates = [row for row in rows if str(row["id"]) not in verified and str(row["id"]) not in old_seen]
        if len(candidates) < 120:
            raise ValueError("Insufficient previously unexecuted candidate tasks")
        groups: dict[str, list[dict]] = {}
        rng = random.Random(SEED)
        for row in candidates:
            groups.setdefault(str(row["instruction_type"]), []).append(row)
        for group in groups.values():
            group.sort(key=lambda row: str(row["id"]))
            rng.shuffle(group)
        quotas = {name: len(group) * 120 // len(candidates) for name, group in groups.items()}
        for name in sorted(groups, key=lambda key: (-(len(groups[key]) * 120 % len(candidates)), key))[:120-sum(quotas.values())]:
            quotas[name] += 1
        selected = [row for name in sorted(groups) for row in groups[name][:quotas[name]]]
        rng.shuffle(selected)
        if len(selected) != 120 or len({str(row["id"]) for row in selected}) != 120:
            raise ValueError("Invalid selected test set")
        runtime = ROOT / "data/spreadsheetbench_fresh_240_runtime"
        split_dir = ROOT / "data/spreadsheetbench_fresh_split"
        manifest_path = ROOT / "data/remem_fresh_test_manifest.json"
        if runtime.exists() or split_dir.exists() or manifest_path.exists():
            raise FileExistsError("Fresh test artifacts exist; do not overwrite them")
        with tempfile.TemporaryDirectory(prefix="remem-fresh-", dir=ROOT / "data") as tmp:
            staged = Path(tmp) / runtime.name
            staged.mkdir()
            for row in train + val:
                relative = PurePosixPath(str(row["spreadsheet_path"]))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe verified task path")
                shutil.copytree(ROOT / "data/spreadsheetbench_remem_400" / Path(*relative.parts),
                                staged / Path(*relative.parts))
            case_counts: Counter[int] = Counter()
            for row in selected:
                relative = PurePosixPath(str(row["spreadsheet_path"]))
                if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "spreadsheet":
                    raise ValueError("Unsafe test task path")
                source_prefix = f"{PREFIX}/{relative.as_posix()}/"
                input_names = sorted(name for name in members if name.startswith(source_prefix) and name.endswith("_input.xlsx"))
                if not input_names:
                    raise ValueError("Missing test workbooks")
                folder = staged / Path(*relative.parts)
                folder.mkdir(parents=True)
                for input_name in input_names:
                    answer_name = input_name[:-len("_input.xlsx")] + "_answer.xlsx"
                    if answer_name not in members:
                        raise ValueError("Missing paired answer workbook")
                    for name, suffix in ((input_name, "_init.xlsx"), (answer_name, "_golden.xlsx")):
                        archive_member = members[name]
                        if archive_member.issym() or archive_member.islnk():
                            raise ValueError("Linked archive member")
                        source = bundle.extractfile(archive_member)
                        if source is None:
                            raise ValueError("Unreadable workbook")
                        destination = folder / (Path(name).name.rsplit("_", 1)[0] + suffix)
                        with source, destination.open("xb") as output:
                            shutil.copyfileobj(source, output)
                        workbook = load_workbook(destination, read_only=True, data_only=True)
                        workbook.close()
                case_counts[len(input_names)] += 1
            staged.rename(runtime)
    for name, items in (("train", train), ("val", val), ("test", selected)):
        write_once(split_dir / name / "items.json", items)
    manifest = {
        "schema_version": 1, "source_revision": REVISION, "archive_sha256": ARCHIVE_SHA256,
        "source_license": "CC-BY-SA-4.0", "selection_seed": SEED,
        "historical_results_files_scanned": scanned,
        "candidate_unseen_ids": len(candidates), "selected_test_count": len(selected),
        "selected_types": dict(Counter(str(row["instruction_type"]) for row in selected)),
        "test_case_counts": dict(case_counts),
        "runtime_data_root": runtime.relative_to(ROOT).as_posix(),
        "split_dir": split_dir.relative_to(ROOT).as_posix(),
        "split_hashes": {name: sha256(split_dir / name / "items.json") for name in ("train", "val", "test")},
        "runtime_files": {path.relative_to(runtime).as_posix(): sha256(path) for path in sorted(runtime.rglob("*")) if path.is_file()},
        "limitations": ["The additional 512 tasks are from the original 912 release, not the human-verified 400 subset.",
                        "No historical CAM results.jsonl includes these selected IDs; other unobserved exposure remains possible.",
                        "Source or template overlap beyond exact duplicates requires review before formal claims."],
    }
    write_once(manifest_path, manifest)
    print(json.dumps({key: value for key, value in manifest.items() if key != "runtime_files"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
