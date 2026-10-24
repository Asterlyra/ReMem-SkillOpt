"""Two proposal strategies with a shared model-call and output boundary."""
from __future__ import annotations

import json
from pathlib import Path

from .evidence import rule_index
from .types import ProposalResult, canonical, digest


class JsonProposalStrategy:
    def __init__(self, repair: bool, call, max_proposals: int):
        self.repair, self.call, self.max_proposals = repair, call, max_proposals

    def propose(self, skill: str, observations: list[dict], memory: list[dict]) -> ProposalResult:
        prompt = (Path(__file__).parent / "prompts" / ("repair.md" if self.repair else "free_edit.md")).read_text(encoding="utf-8")
        request = {"skill": skill, "skill_before_hash": digest(skill), "current_training_observations": observations,
                   "history": memory, "max_proposals": self.max_proposals}
        if self.repair:
            request["rules"] = rule_index(skill)
        text = self.call(prompt, canonical(request))
        try:
            result = json.loads(text)
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
            return ProposalResult(**result)
        except (ValueError, TypeError, RecursionError):
            return ProposalResult("proposal_invalid", reason="invalid_json_or_response_contract")
