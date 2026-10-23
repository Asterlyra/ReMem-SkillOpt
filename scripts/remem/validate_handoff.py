"""Validate the research handoff offline; never invokes model APIs or training."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    errors: list[str] = []
    required = [
        "README.md", "UPSTREAM_README.md", "START_HERE.md", "HANDOFF.md", "AGENTS.md",
        "LICENSE", "research/remem/study_design.json", "research/remem/provenance.json",
        "research/remem/references.bib", "research/remem/model.env.example",
    ]
    required += [f"docs/remem/{name}.md" for name in (
        "01_BACKGROUND", "02_METHOD", "03_IMPLEMENTATION_PLAN", "04_EXPERIMENT_PROTOCOL",
        "05_METRICS", "06_MODEL_REGISTRY", "07_RELATED_WORK", "08_CAM_REUSE",
        "09_REPRODUCIBILITY",
    )]
    for name in required:
        if not (root / name).is_file():
            errors.append(f"Missing: {name}")
    if errors:
        raise SystemExit("\n".join(errors))

    design = json.loads((root / "research/remem/study_design.json").read_text(encoding="utf-8"))
    provenance = json.loads((root / "research/remem/provenance.json").read_text(encoding="utf-8"))
    core = [a for a in design["arms"] if a["family"] == "core"]
    if {(a["R"], a["M"]) for a in core} != {(False, False), (True, False), (False, True), (True, True)} or len(core) != 4:
        errors.append("Core matrix is not a complete unique 2x2 design")
    if len(set(design["seeds"])) != 3:
        errors.append("Expected three unique training seeds")
    ids = [a["id"] for a in design["arms"]]
    if len(set(ids)) != len(ids):
        errors.append("Duplicate arm ID")
    for variant, spec in design["variants"].items():
        if not set(spec["omit_arms"]).issubset(ids):
            errors.append(f"Unknown omitted arm: {variant}")
        n = sum(a not in spec["omit_arms"] for a in ids) * len(design["seeds"])
        if n != spec["optimization_runs"]:
            errors.append(f"Incorrect matrix size: {variant}")
    schedule, data = design["schedule"], design["data"]
    if schedule["first_pass_steps"] * schedule["batch_size"] != data["train_unique"]:
        errors.append("Initial train coverage mismatch")
    if schedule["revisit_steps"] * schedule["batch_size"] != schedule["revisit_unique"]:
        errors.append("Revisit coverage mismatch")
    estimated = schedule["steps"] * schedule["batch_size"] + (schedule["steps"] + 1) * data["selection_unique"]
    if estimated != design["budget"]["optimization_task_executions_per_run"]:
        errors.append("Reference task-execution budget mismatch")

    for name in required:
        path = root / name
        if path.suffix != ".md" or name == "UPSTREAM_README.md":
            continue
        body = path.read_text(encoding="utf-8")
        for dest in re.findall(r"\]\(([^)]+)\)", body):
            if dest.startswith(("http:", "https:", "mailto:", "#")):
                continue
            target = dest.split("#", 1)[0]
            if target and not (path.parent / target).resolve().exists():
                errors.append(f"Broken local link in {name}: {target}")

    template = (root / "research/remem/model.env.example").read_text(encoding="utf-8")
    for line in template.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.endswith("API_KEY") and value.strip():
            errors.append("Credential template has a nonempty key")
    # Check only newly authored handoff files, never print matching secret text.
    secret_pattern = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})")
    for name in required:
        if name == "UPSTREAM_README.md":
            continue
        if secret_pattern.search((root / name).read_text(encoding="utf-8")):
            errors.append(f"Possible secret in {name}")

    for name in (".env", ".env.local", "configs/local/credentials.yaml", "outputs/example.json"):
        result = subprocess.run(["git", "check-ignore", "--quiet", name], cwd=root, check=False)
        if result.returncode != 0:
            errors.append(f"Sensitive/runtime path is not ignored: {name}")
    upstream_readme = hashlib.sha256(
        (root / "UPSTREAM_README.md").read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    if upstream_readme != provenance["upstream"]["readme_sha256"]:
        errors.append("Preserved upstream README differs from source fingerprint")
    if errors:
        raise SystemExit("\n".join(errors))
    print(json.dumps({"status": "passed", "scope": "handoff_structure_only", "required_files": len(required),
                      "core_runs": len(core) * len(design["seeds"]),
                      "recommended_runs": design["variants"]["recommended_21"]["optimization_runs"],
                      "model_calls": 0, "algorithms_implemented": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
