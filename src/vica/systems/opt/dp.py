"""Exact DP baseline for OPT-v0.1 (traditional precise solver).

Uses a bitmask (Held-Karp style) dynamic program to compute the minimum total
tardiness over all permutations:

    dp[mask] = min over j in mask of dp[mask - {j}] + max(0, time[mask] - d_j)

where time[mask] is the sum of processing times of jobs in mask (the finish
time of the last job in mask). Complexity O(n * 2^n); feasible for n <= ~20.
"""

from __future__ import annotations

from typing import Any

from vica.protocol.models import SolveOutput


def optimal_order(processing: list[int], deadlines: list[int]) -> list[int]:
    """Return an optimal permutation minimizing total tardiness."""
    n = len(processing)
    size = 1 << n
    total_p = [0] * size
    for mask in range(1, size):
        lsb = mask & -mask
        i = lsb.bit_length() - 1
        total_p[mask] = total_p[mask ^ lsb] + processing[i]

    INF = float("inf")
    dp = [INF] * size
    dp[0] = 0.0
    parent = [-1] * size
    for mask in range(1, size):
        t = total_p[mask]
        best = INF
        best_j = -1
        m = mask
        while m:
            lsb = m & -m
            j = lsb.bit_length() - 1
            m ^= lsb
            prev = mask ^ lsb
            if dp[prev] != INF:
                cand = dp[prev] + max(0, t - deadlines[j])
                if cand < best:
                    best = cand
                    best_j = j
        dp[mask] = best
        parent[mask] = best_j

    order: list[int] = []
    mask = size - 1
    while mask:
        j = parent[mask]
        order.append(j)
        mask ^= 1 << j
    order.reverse()
    return order


class DpOptSystem:
    """Exact DP solver; the precise traditional baseline."""

    system_id = "opt-dp"

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        payload = challenge.get("payload", {})
        processing = payload.get("processing")
        deadlines = payload.get("deadlines")
        if not isinstance(processing, list) or not isinstance(deadlines, list):
            raise ValueError("DpOptSystem expects an opt-v0.1 payload")
        order = optimal_order(processing, deadlines)
        return SolveOutput(
            candidate={"order": order},
            metadata={"strategy": "dp-exact"},
        )


__all__ = ["DpOptSystem", "optimal_order"]