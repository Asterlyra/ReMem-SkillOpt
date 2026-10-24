"""Audit historical SpreadsheetBench ID exposure without reading old scores."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=Path("E:/Programs/CAM/CAM-SkillOpt"))
    parser.add_argument("--output", type=Path, default=Path("research/remem/exposure_audit.json"))
    args = parser.parse_args()
    pool_root = Path("data/spreadsheetbench_split")
    splits = {name: {str(row["id"]) for row in json.loads((pool_root / name / "items.json").read_text(encoding="utf-8"))}
              for name in ("train", "val", "test")}
    if any(splits[a] & splits[b] for a, b in (("train", "val"), ("train", "test"), ("val", "test"))):
        raise ValueError("Overlapping split IDs")
    seen: set[str] = set()
    test_named: set[str] = set()
    seen_any: set[str] = set()
    evidence: list[dict] = []
    index = hashlib.sha256()
    scanned = 0
    for path in sorted((args.reference / "outputs").rglob("results.jsonl")):
        scanned += 1
        ids: set[str] = set()
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and "id" in value:
                    ids.add(str(value["id"]))
        index.update(path.relative_to(args.reference).as_posix().encode("utf-8"))
        index.update(sha256(path).encode("ascii"))
        seen_any.update(ids)
        exposed = ids & splits["test"]
        if not exposed:
            continue
        seen.update(exposed)
        if any("test" in part.lower() for part in path.parts):
            test_named.update(exposed)
        evidence.append({"relative_path": path.relative_to(args.reference).as_posix(),
                         "sha256": sha256(path), "test_pool_ids": len(exposed)})
    # Scores, answers and individual test IDs are deliberately absent.
    archive = Path("data/downloads/spreadsheetbench_912_v0.1.tar.gz")
    if sha256(archive) != "9cf7228b54f1edcdd4b372eb736774adf29cb4f804c9920229bac6c154833399":
        raise ValueError("Pinned 912-task archive hash mismatch")
    with tarfile.open(archive) as bundle:
        source = bundle.extractfile("all_data_912_v0.1/dataset.json")
        if source is None:
            raise ValueError("Pinned 912 dataset metadata missing")
        full_ids = {str(row["id"]) for row in json.load(source)}
    verified_ids = splits["train"] | splits["val"] | splits["test"]
    if len(full_ids) != 912 or len(full_ids & verified_ids) != 400:
        raise ValueError("Unexpected full/verified task overlap")
    additional_ids = full_ids - verified_ids
    report = {
        "schema_version": 2, "reference_label": "read-only local CAM-SkillOpt outputs",
        "scanned_results_files": scanned,
        "results_index_sha256": index.hexdigest(),
        "split_sizes": {name: len(ids) for name, ids in splits.items()},
        "historically_exposed_test_pool_count": len(seen),
        "test_named_exposed_count": len(test_named),
        "unseen_test_pool_count": len(splits["test"] - seen),
        "clean_final_120_available": len(splits["test"] - seen) >= 120,
        "additional_912_task_ids": len(additional_ids),
        "additional_seen_in_old_results": len(additional_ids & seen_any),
        "additional_unseen_in_old_results": len(additional_ids - seen_any),
        "evidence": evidence,
        "limits": ["This audits old results.jsonl task IDs and paths, not every historical prompt or private run.",
                   "All 280 current test-pool IDs appear in old results; this alone rules out a never-used final 120 from that pool."],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "evidence"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
