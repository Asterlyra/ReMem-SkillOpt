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


def _resolve(ref: dict, visible_events: set[str], store: EventStore) -> tuple[dict, dict] | None:
    """Return (event, artifact) only when the reference is valid exactly as written."""
    event_id = ref.get("event_id")
    if event_id not in visible_events:
        return None
    event = store.get(event_id)
    if not event or event.get("source_split") != "train" or event.get("artifact_hash") != ref.get("artifact_hash"):
        return None
    try:
        artifact = store.read_artifact(ref["artifact_hash"])
    except (ValueError, KeyError):
        return None
    quote = ref.get("quote")
    if not isinstance(quote, str) or quote not in artifact.get("trace", ""):
        return None
    return event, artifact


def _rebind(quote: str, visible_events: set[str], store: EventStore) -> list[tuple[str, str]]:
    """Visible training events whose recorded trace contains ``quote`` verbatim.

    Only events already inside the permitted training context are considered, so
    re-binding can never widen what the optimizer was allowed to see.
    """
    matches: list[tuple[str, str]] = []
    for event_id in sorted(visible_events):
        event = store.get(event_id)
        if not event or event.get("source_split") != "train":
            continue
        try:
            artifact = store.read_artifact(event["artifact_hash"])
        except (ValueError, KeyError):
            continue
        if quote in artifact.get("trace", ""):
            matches.append((event_id, event["artifact_hash"]))
    return matches


def validate_proposal(proposal: dict, skill: str, visible_events: set[str], store: EventStore) -> list[dict]:
    """Validate an evidence-bound repair proposal.

    Returns the list of evidence re-bindings that were needed, so the caller can
    record them. A quote that exists verbatim in exactly one *visible* training
    trace is re-bound to that trace: pairing a real quote with the wrong artifact
    is a clerical mistake, not fabricated evidence, and previously it discarded
    the entire proposal — including the ones citing the most evidence. A quote
    found nowhere visible, or ambiguously in several traces, is still rejected,
    so the "evidence must be real and inside the permitted context" rule holds.
    """
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
    repairs: list[dict] = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict) or set(ref) != {"event_id", "artifact_hash", "quote"}:
            raise ValueError("Invalid evidence reference")
        quote = ref["quote"]
        if not isinstance(quote, str) or len(quote.strip()) < 8:
            raise ValueError("Evidence quote is not present in the recorded trace")
        resolved = _resolve(ref, visible_events, store)
        if resolved is None:
            candidates = _rebind(quote, visible_events, store)
            if len(candidates) == 1:
                event_id, artifact_hash = candidates[0]
                repairs.append({"index": index,
                                "from": {"event_id": ref["event_id"], "artifact_hash": ref["artifact_hash"]},
                                "to": {"event_id": event_id, "artifact_hash": artifact_hash}})
                ref["event_id"], ref["artifact_hash"] = event_id, artifact_hash
                resolved = _resolve(ref, visible_events, store)
            elif not candidates:
                if ref["event_id"] not in visible_events:
                    raise ValueError("Evidence outside current permitted training context")
                raise ValueError("Evidence quote is not present in the recorded trace")
            else:
                raise ValueError("Evidence quote matches multiple visible training artifacts")
        event, _artifact = resolved
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
    return repairs
