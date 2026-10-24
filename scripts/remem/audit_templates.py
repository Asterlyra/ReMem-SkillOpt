"""Check exact cross-split workbook and instruction duplicates, without scores."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path("data/spreadsheetbench_remem_400"))
    parser.add_argument("--split-dir", type=Path, default=Path("data/spreadsheetbench_split"))
    parser.add_argument("--output", type=Path, default=Path("research/remem/template_audit.json"))
    args = parser.parse_args()
    root = args.runtime
    splits = args.split_dir
    books: dict[str, set[str]] = defaultdict(set)
    prompts: dict[str, set[str]] = defaultdict(set)
    missing: list[str] = []
    instruction_tokens: dict[str, list[set[str]]] = defaultdict(list)
    for split in ("train", "val", "test"):
        items = json.loads((splits / split / "items.json").read_text(encoding="utf-8"))
        for item in items:
            task = str(item["id"])
            folder = root / str(item["spreadsheet_path"])
            initial = list(folder.glob("*_init.xlsx")) + list(folder.glob("initial.xlsx"))
            if not initial:
                missing.append(task)
            else:
                for book in initial:
                    books[digest(book)].add(split)
            normalized = re.sub(r"\s+", " ", str(item["instruction"]).casefold()).strip()
            prompts[normalized].add(split)
            instruction_tokens[split].append(set(re.findall(r"[a-z0-9]+", normalized)))
    cross_books = sum(len(value) > 1 for value in books.values())
    cross_prompts = sum(len(value) > 1 for value in prompts.values())
    prior = instruction_tokens["train"] + instruction_tokens["val"]
    nearest = [max((len(tokens & other) / len(tokens | other) if tokens | other else 1)
                   for other in prior) for tokens in instruction_tokens["test"]]
    report = {"scope": "exact_cross_split_duplicate_screen", "runtime": str(root),
              "tasks_missing_initial_books": len(missing),
              "distinct_initial_book_hashes": len(books), "cross_split_identical_books": cross_books,
              "cross_split_identical_instructions": cross_prompts,
              "test_to_train_val_max_token_jaccard": round(max(nearest), 4),
              "test_items_with_token_jaccard_ge_0_8": sum(score >= 0.8 for score in nearest),
              "source_template_group_status": "unknown",
              "limit": "Exact equality cannot rule out related source workbooks or templates with changed cells or wording."}
    path = args.output
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
