"""Benchmark statistics (docs/BENCHMARK_METHODOLOGY.md).

Implements the v0.2 reporting math without SciPy:

- Wilson score interval (95%) for binomial success rate;
- latency distribution (mean / median / p50 / p95);
- known-cost coverage;
- report-level failure taxonomy aggregation (per difficulty);
- paired challenge comparison between two systems.

Conventions: 0-sample cells report ``None`` (N/A) rather than crashing or
fabricating a degenerate interval. Unknown cost stays UNKNOWN (never 0).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any

from vica.eval.models import ReportStatus, ResultRecord

# 95% two-sided confidence level.
_Z = 1.96


def wilson_interval(successes: int, n: int, z: float = _Z) -> tuple[float | None, float | None]:
    """Wilson score 95% confidence interval for a binomial proportion.

    Returns ``(lower, upper)`` clipped to [0, 1], or ``(None, None)`` when
    ``n == 0`` (the point estimate is undefined, not 0).
    """
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n) / denom
    return max(0.0, center - half), min(1.0, center + half)


def success_rate_with_ci(
    successes: int, n: int
) -> dict[str, float | None]:
    """Point estimate + 95% Wilson CI for a success rate."""
    lo, hi = wilson_interval(successes, n)
    return {
        "success_rate": successes / n if n else None,
        "ci_lower": lo,
        "ci_upper": hi,
        "n": n,
    }


def latency_distribution(values: list[float]) -> dict[str, float | None]:
    """mean / median (p50) / p95 of a latency sample."""
    if not values:
        return {"mean": None, "p50": None, "p95": None, "n": 0}
    ordered = sorted(values)
    return {
        "mean": statistics.fmean(values),
        "p50": statistics.median(values),
        "p95": _percentile(ordered, 95),
        "n": len(values),
    }


def _percentile(ordered: list[float], p: int) -> float:
    rank = max(1, min(len(ordered), int(math.ceil(p / 100 * len(ordered)))))
    return ordered[rank - 1]


def cost_coverage(records: list[ResultRecord]) -> dict[str, float | int | None]:
    """Fraction of instances with a known (non-None) cost.

    ``N/A`` cost is correct but does not tell a reader how much data actually
    carries a cost, so we report ``cost_coverage = known / total``.
    """
    total = len(records)
    known = 0
    for r in records:
        cost = r.metadata.get("estimated_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            known += 1
    return {"known": known, "total": total, "cost_coverage": known / total if total else None}


def failure_taxonomy(records: list[ResultRecord]) -> dict[str, Any]:
    """Per-status counts and rates, plus failure breakdown by difficulty."""
    status_counts: dict[str, int] = defaultdict(int)
    by_difficulty: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "valid": 0, "statuses": defaultdict(int)}
    )
    for r in records:
        status_counts[r.status.value] += 1
        cell = by_difficulty[r.difficulty]
        cell["total"] += 1
        if r.status == ReportStatus.VALID:
            cell["valid"] += 1
        cell["statuses"][r.status.value] += 1

    total = len(records)
    merged: dict[str, Any] = {
        "total": total,
        "counts": dict(status_counts),
        "rates": {
            k: v / total if total else None for k, v in status_counts.items()
        },
        "by_difficulty": {},
    }
    for diff, cell in sorted(by_difficulty.items()):
        d_total = cell["total"]
        merged["by_difficulty"][str(diff)] = {
            "total": d_total,
            "valid": cell["valid"],
            "valid_rate": cell["valid"] / d_total if d_total else None,
            "statuses": dict(cell["statuses"]),
        }
    return merged


def paired_comparison(
    system_a: str,
    results_a: dict[str, ResultRecord],
    system_b: str,
    results_b: dict[str, ResultRecord],
) -> dict[str, Any]:
    """Paired comparison of two systems on the same challenge ids.

    Systems should run the same challenge set; only challenges present in both
    are compared. Returns counts for A-wins / B-wins / tie / both-fail.
    """
    common = [cid for cid in results_a if cid in results_b]
    a_wins = b_wins = tie = both_fail = 0
    for cid in common:
        a = results_a[cid]
        b = results_b[cid]
        if not a.valid and not b.valid:
            both_fail += 1
        elif a.valid and b.valid:
            if a.score > b.score:
                a_wins += 1
            elif b.score > a.score:
                b_wins += 1
            else:
                tie += 1
        elif a.valid:
            a_wins += 1
        else:
            b_wins += 1
    return {
        "system_a": system_a,
        "system_b": system_b,
        "compared": len(common),
        "a_wins": a_wins,
        "b_wins": b_wins,
        "tie": tie,
        "both_fail": both_fail,
    }


__all__ = [
    "cost_coverage",
    "failure_taxonomy",
    "latency_distribution",
    "paired_comparison",
    "success_rate_with_ci",
    "wilson_interval",
]