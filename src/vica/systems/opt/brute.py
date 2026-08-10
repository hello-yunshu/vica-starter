"""Enumerative brute-force baseline for OPT-v0.1.

Exhaustively searches all permutations and returns the highest-scoring one.
Feasible for small n; for deeper instances it hits the time budget and
returns the best found so far (traditional-but-slow solver).
"""

from __future__ import annotations

import itertools
import time
from typing import Any

from vica.challenges.opt_v01.family import score_order
from vica.protocol.models import SolveOutput


class BruteOptSystem:
    """Exhaustive permutation search; the naive traditional baseline."""

    system_id = "opt-brute"

    def __init__(self, max_seconds: float = 10.0) -> None:
        self.max_seconds = max_seconds

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        payload = challenge.get("payload", {})
        processing = payload.get("processing")
        deadlines = payload.get("deadlines")
        n = payload.get("n")
        if not isinstance(processing, list) or not isinstance(deadlines, list):
            raise ValueError("BruteOptSystem expects an opt-v0.1 payload")
        if not isinstance(n, int) or n != len(processing) or n != len(deadlines):
            raise ValueError("BruteOptSystem: inconsistent opt-v0.1 payload")

        start = time.perf_counter()
        best_score: int | None = None
        best_order: list[int] | None = None
        for perm in itertools.permutations(range(n)):
            if time.perf_counter() - start > self.max_seconds:
                break
            s = score_order(processing, deadlines, list(perm))
            if best_score is None or s > best_score:
                best_score = s
                best_order = list(perm)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        candidate = {"order": best_order} if best_order is not None else None
        return SolveOutput(
            candidate=candidate,
            metadata={
                "strategy": "brute-force-enum",
                "solve_wall_time_ms": elapsed_ms,
            },
        )


__all__ = ["BruteOptSystem"]