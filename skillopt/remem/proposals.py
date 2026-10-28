"""Two proposal strategies with a shared model-call and output boundary."""
from __future__ import annotations

import json
import re
from pathlib import Path

from skillopt.utils.json_utils import extract_json

from .evidence import rule_index
from .types import ProposalResult, canonical, digest


def classify_reply(text: str) -> tuple[dict | None, str]:
    """Parse an optimizer reply and report how much tolerance it needed.

    Optimizer models frequently wrap a perfectly valid JSON object in a Markdown
    code fence. The frozen contract used to treat that as ``invalid_json``, which
    discarded the whole proposal step over a formatting habit that carries no
    information about the method under test. The fence is therefore stripped, and
    how it was recovered is recorded rather than silently accepted, so a study can
    still tell "the model produced bare JSON" apart from "a fence was removed".
    """
    parsed = extract_json(text)
    if parsed is None:
        return None, "no_json"
    stripped = text.strip()
    try:
        json.loads(stripped)
        return parsed, "bare_json"
    except json.JSONDecodeError:
        pass
    fence = re.match(r"^```[A-Za-z0-9_-]*\s*\n?(.*?)\n?```$", stripped, re.DOTALL)
    if fence:
        try:
            json.loads(fence.group(1))
            return parsed, "fenced_json"
        except json.JSONDecodeError:
            pass
    return parsed, "repaired_json"


class JsonProposalStrategy:
    def __init__(self, repair: bool, call, max_proposals: int):
        self.repair, self.call, self.max_proposals = repair, call, max_proposals
        self.reply_parse = "no_json"

    def propose(self, skill: str, observations: list[dict], memory: list[dict]) -> ProposalResult:
        prompt = (Path(__file__).parent / "prompts" / ("repair.md" if self.repair else "free_edit.md")).read_text(encoding="utf-8")
        request = {"skill": skill, "skill_before_hash": digest(skill), "current_training_observations": observations,
                   "history": memory, "max_proposals": self.max_proposals}
        if self.repair:
            request["rules"] = rule_index(skill)
        text = self.call(prompt, canonical(request))
        parsed, self.reply_parse = classify_reply(text)
        if parsed is None:
            return ProposalResult("proposal_invalid", reason="invalid_json", parse=self.reply_parse)
        try:
            result = parsed
            if not isinstance(result, dict) or set(result) != {"status", "reason", "proposals"}:
                raise ValueError("Expected status, reason and proposals")
            if not isinstance(result["reason"], str) or not isinstance(result["proposals"], list):
                raise ValueError("Invalid response fields")
            if result["status"] == "no_change":
                if result["proposals"] or not result["reason"].strip():
                    raise ValueError("no_change requires a reason and no proposals")
            elif result["status"] == "proposals":
                if not 0 < len(result["proposals"]) <= self.max_proposals:
                    raise ValueError("Proposal count exceeds contract")
            else:
                raise ValueError("Unknown response status")
            return ProposalResult(**result, parse=self.reply_parse)
        except (ValueError, TypeError, RecursionError):
            return ProposalResult("proposal_invalid", reason="invalid_response_contract", parse=self.reply_parse)
