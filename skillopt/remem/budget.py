"""Deterministic bounded selection preserving rejected candidates and reasons."""
from __future__ import annotations

from .types import canonical


def select(proposals: list[dict], limit: int, *, repair: bool) -> tuple[list[dict], list[dict]]:
    chosen, audit, seen, anchors = [], [], set(), []
    for proposal in proposals:
        edit = proposal["patch"] if repair else proposal
        key, target = canonical(edit), edit.get("target", "")
        reason = "selected"
        if key in seen:
            reason = "duplicate"
        elif target and any(target in previous or previous in target for previous in anchors):
            reason = "conflicting_anchor_alternative"
        elif len(chosen) >= limit:
            reason = "edit_budget"
        seen.add(key)
        audit.append({"proposal": proposal, "decision": reason})
        if reason == "selected":
            chosen.append(proposal)
            if target:
                anchors.append(target)
    return chosen, audit
