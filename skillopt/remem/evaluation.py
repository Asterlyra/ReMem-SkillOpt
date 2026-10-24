"""Paired selection gate. No validation task content is returned to proposals."""
from __future__ import annotations

import math

import numpy as np


def aligned_scores(rows: list[dict]) -> dict[str, float]:
    scores = {}
    for row in rows:
        task = str(row["id"])
        score = row.get("hard")
        if task in scores or not isinstance(score, (float, int)) or not math.isfinite(score) or score not in (0, 1):
            raise ValueError("Invalid or duplicate selection outcome")
        if row.get("outcome") == "infra_failure" or row.get("llm_ok") is False:
            raise ValueError("Infrastructure failure is not a selection score")
        scores[task] = float(score)
    if not scores:
        raise ValueError("Empty selection evidence")
    return scores


class PairedBootstrapGate:
    def __init__(self, samples: int = 10000, confidence: float = .95, seed: int = 0):
        self.samples, self.confidence, self.seed = samples, confidence, seed

    def compare(self, before: list[dict], candidate: list[dict]) -> dict:
        left, right = aligned_scores(before), aligned_scores(candidate)
        if set(left) != set(right):
            raise ValueError("Selection task IDs do not align")
        delta = np.array([right[k] - left[k] for k in sorted(left)])
        rng = np.random.default_rng(self.seed)
        draws = delta[rng.integers(0, len(delta), size=(self.samples, len(delta)))].mean(axis=1)
        low, high = np.quantile(draws, [(1-self.confidence)/2, (1+self.confidence)/2])
        action = "accept" if low > 0 else ("reject" if high < 0 else "inconclusive")
        return {"action": action, "mean_delta": float(delta.mean()), "lower": float(low), "upper": float(high),
                "n": len(delta), "samples": self.samples, "confidence": self.confidence}
