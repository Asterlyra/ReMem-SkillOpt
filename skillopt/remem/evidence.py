"""Source and anchor checks. These checks do not prove diagnostic semantics."""
from __future__ import annotations

from .store import EventStore
from .types import canonical, digest

OPERATORS = {
    "ADD_RULE": {"append", "insert_after"}, "CORRECT_RULE": {"replace"},
    "ADD_SCOPE": {"replace"}, "MAKE_ACTION_EXPLICIT": {"replace", "insert_after"},
    "ADD_CHECK": {"append", "insert_after"}, "REMOVE_CONFLICT": {"delete", "replace"},
}
DIAGNOSES = {"missing_rule", "wrong_rule", "scope_error", "execution_lapse", "missing_check", "unknown"}


def rule_index(skill: str) -> dict[str, str]:
    rules = {f"rule_{i}_{digest(line)[:12]}": line for i, line in enumerate(skill.splitlines()) if line.strip()}
    return {"document_end": "", **rules}


def validate_edit(edit: dict, skill: str) -> None:
    if not isinstance(edit, dict) or set(edit) - {"op", "target", "content"}:
        raise ValueError("Invalid edit fields")
    if edit.get("op") not in {"append", "insert_after", "replace", "delete"}:
        raise ValueError("Unknown edit operation")
    if any(not isinstance(edit.get(k, ""), str) for k in ("target", "content")):
        raise ValueError("Edit target/content must be strings")
    target = edit.get("target", "")
    if edit["op"] != "append" and (not target or skill.count(target) != 1):
        raise ValueError("Edit requires a unique exact anchor")
    if edit["op"] != "delete" and not edit.get("content", "").strip():
        raise ValueError("Empty edit content")
    if edit["op"] == "append" and target:
        raise ValueError("Append must target document_end")
    if edit["op"] in {"append", "insert_after"} and edit.get("content", "").strip() in skill:
        raise ValueError("Edit duplicates existing skill content")
    if any(marker in (target + edit.get("content", "")) for marker in ("<!-- SLOW_UPDATE", "<!-- APPENDIX")):
        raise ValueError("Protected region marker")


def validate_proposal(proposal: dict, skill: str, visible_events: set[str], store: EventStore) -> None:
    required = {"proposal_id", "skill_before_hash", "failure_case_ids", "evidence_refs", "diagnosis",
                "target_rule_id", "repair_operator", "patch", "expected_observation", "preserve_cases"}
    if not isinstance(proposal, dict) or set(proposal) != required:
        raise ValueError("Proposal fields must exactly match the contract")
    for field in ("proposal_id", "expected_observation", "target_rule_id", "repair_operator"):
        if not isinstance(proposal[field], str) or not proposal[field].strip():
            raise ValueError(f"Missing proposal field: {field}")
    if proposal["skill_before_hash"] != digest(skill):
        raise ValueError("Stale skill version")
    if proposal["diagnosis"] not in DIAGNOSES or proposal["diagnosis"] == "unknown":
        raise ValueError("Insufficient diagnosis for an edit")
    if proposal["diagnosis"] == "execution_lapse" and proposal["repair_operator"] not in {"MAKE_ACTION_EXPLICIT", "ADD_SCOPE"}:
        raise ValueError("An execution lapse does not establish a missing rule")
    if not isinstance(proposal["failure_case_ids"], list) or not proposal["failure_case_ids"]:
        raise ValueError("A repair needs a real failure case")
    refs = proposal["evidence_refs"]
    if not isinstance(refs, list) or not refs:
        raise ValueError("Evidence is required")
    supported = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"event_id", "artifact_hash", "quote"}:
            raise ValueError("Invalid evidence reference")
        if ref["event_id"] not in visible_events:
            raise ValueError("Evidence outside current permitted training context")
        event = store.get(ref["event_id"])
        if not event or event.get("source_split") != "train" or event.get("artifact_hash") != ref["artifact_hash"]:
            raise ValueError("Unknown training evidence")
        artifact = store.read_artifact(ref["artifact_hash"])
        quote = ref["quote"]
        if not isinstance(quote, str) or len(quote.strip()) < 8 or quote not in artifact["trace"]:
            raise ValueError("Evidence quote is not present in the recorded trace")
        if event["outcome"] == "failure":
            supported.add(digest(canonical([event["task_id"], event["failure_kind"]])))
    if not set(proposal["failure_case_ids"]).issubset(supported):
        raise ValueError("Unsubstantiated failure case")
    if not isinstance(proposal["preserve_cases"], list):
        raise ValueError("preserve_cases must be a list of success event IDs")
    for event_id in proposal["preserve_cases"]:
        event = store.get(event_id) if isinstance(event_id, str) else None
        if event_id not in visible_events or not event or event.get("outcome") != "success":
            raise ValueError("Preservation case is not a visible training success")
    edit = proposal["patch"]
    validate_edit(edit, skill)
    if edit["op"] not in OPERATORS.get(proposal["repair_operator"], set()):
        raise ValueError("Repair operator does not match edit")
    rules = rule_index(skill)
    if proposal["target_rule_id"] not in rules or rules[proposal["target_rule_id"]] != edit.get("target", ""):
        raise ValueError("Rule ID and exact version anchor disagree")
