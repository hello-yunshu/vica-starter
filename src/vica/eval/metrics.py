"""Result Bundle metrics summary (docs/BENCHMARK_METHODOLOGY.md).

``summarize`` turns a list of authoritative ``ResultRecord`` into a portable,
self-contained metrics document embedded in a Result Bundle. It deliberately
avoids a single composite score: it reports correctness, quality, latency,
cost coverage and failure taxonomy as separate dimensions so a benchmark
report never manufactures a leaderboard illusion.

All math lives in ``vica.eval.stats`` (Wilson CI, latency distribution, cost
coverage, failure taxonomy, paired comparison). Unknown costs stay UNKNOWN
(never coerced to 0); 0-sample cells are ``None`` (N/A), never a crash.
"""

from __future__ import annotations

from typing import Any

from vica.eval.models import ResultRecord
from vica.eval.stats import (
    cost_coverage,
    failure_taxonomy,
    latency_distribution,
    success_rate_with_ci,
)


def summarize(records: list[ResultRecord]) -> dict[str, Any]:
    """Aggregate authoritative results into a metrics document.

    The returned dict is JSON-serializable via the protocol's canonical
    serialization and is stored as ``metrics.json`` in a Result Bundle.
    """
    n = len(records)
    valid = sum(1 for r in records if r.valid)

    # Correctness: point estimate + 95% Wilson CI.
    correctness = success_rate_with_ci(valid, n)
    correctness["valid"] = valid

    # Quality: mean OPT regret over valid OPT runs (N/A when absent).
    regrets = [
        float(r.metadata["regret"])
        for r in records
        if isinstance(r.metadata.get("regret"), (int, float))
        and not isinstance(r.metadata.get("regret"), bool)
    ]
    quality: dict[str, Any] = {
        "mean_regret": _mean(regrets) if regrets else None,
        "regret_instances": len(regrets),
    }

    # Latency: wall-clock solve time distribution (mean / p50 / p95).
    latency = latency_distribution([r.solve_wall_time_ms for r in records])

    # Cost: known-cost coverage (UNKNOWN stays UNKNOWN).
    costs = cost_coverage(records)

    # Failure taxonomy: per-status + per-difficulty breakdown.
    taxonomy = failure_taxonomy(records)

    # Per-difficulty correctness with CI.
    by_difficulty: dict[str, Any] = {}
    by_diff: dict[int, list[bool]] = {}
    for r in records:
        by_diff.setdefault(r.difficulty, []).append(r.valid)
    for diff in sorted(by_diff):
        vs = by_diff[diff]
        row = success_rate_with_ci(sum(vs), len(vs))
        row["valid"] = sum(vs)
        by_difficulty[str(diff)] = row

    # Per-task-kind and per-template correctness with CI (REPO family). The
    # task_kind / template are read from each record's non-secret metadata.
    by_task_kind = _layered(records, "task_kind")
    by_template = _layered(records, "template")

    return {
        "sample_count": n,
        "correctness": correctness,
        "quality": quality,
        "latency": latency,
        "cost": costs,
        "failure_taxonomy": taxonomy,
        "by_difficulty": by_difficulty,
        "by_task_kind": by_task_kind,
        "by_template": by_template,
    }


def _layered(records: list[ResultRecord], key: str) -> dict[str, Any]:
    """Aggregate correctness per ``metadata[key]`` label (e.g. task_kind)."""
    buckets: dict[str, list[bool]] = {}
    for r in records:
        label = r.metadata.get(key)
        if isinstance(label, str) and label:
            buckets.setdefault(label, []).append(r.valid)
    out: dict[str, Any] = {}
    for label in sorted(buckets):
        vs = buckets[label]
        row = success_rate_with_ci(sum(vs), len(vs))
        row["valid"] = sum(vs)
        out[label] = row
    return out


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


__all__ = ["summarize"]