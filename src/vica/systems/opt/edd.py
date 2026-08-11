"""Earliest-due-date greedy baseline for OPT-v0.1.

EDD is optimal for 1||Lmax but not for 1||sum T_j, so it is a good
traditional heuristic comparison point (better than random, below optimal).
"""

from __future__ import annotations

from typing import Any

from vica.protocol.models import SolveOutput


class EddSystem:
    """Order jobs by non-decreasing due date."""

    system_id = "opt-edd"
    supported_challenge_types: frozenset[str] = frozenset({"opt-v0.1"})

    def config(self) -> dict[str, Any]:
        return {"strategy": "edd"}

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        payload = challenge.get("payload", {})
        deadlines = payload.get("deadlines")
        if not isinstance(deadlines, list):
            raise ValueError("EddSystem expects an opt-v0.1 payload with deadlines")
        order = sorted(range(len(deadlines)), key=lambda i: deadlines[i])
        return SolveOutput(
            candidate={"order": order},
            metadata={"strategy": "edd"},
        )


__all__ = ["EddSystem"]