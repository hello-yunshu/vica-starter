"""CSV / JSON export of experiment runs."""

from __future__ import annotations

import csv
import json
from typing import TextIO

from vica.arena.metrics import SystemMetrics, aggregate
from vica.protocol.models import RunRecord


def _round_opt(value: float | None, ndigits: int) -> float | None:
    """Round a metric, preserving ``None`` (UNKNOWN cost) as N/A."""
    return round(value, ndigits) if value is not None else None


_COLUMNS = [
    "experiment_id",
    "challenge_id",
    "challenge_type",
    "difficulty",
    "seed",
    "system_id",
    "valid",
    "score",
    "solve_wall_time_ms",
    "verify_time_us",
    "error_code",
    "strategy",
    "status",
    "attempts",
    "rounds",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
    "model",
]


def write_runs_csv(records: list[RunRecord], fh: TextIO) -> None:
    writer = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow(_record_to_row(r))


def write_runs_json(records: list[RunRecord], fh: TextIO) -> None:
    # allow_nan=False keeps export consistent with the protocol, which forbids
    # NaN/Infinity (SPEC "Data interchange"); any such value is a hard error
    # rather than a silent, non-portable JSON emit.
    json.dump(
        [_record_to_row(r) for r in records],
        fh,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def write_metrics_csv(records: list[RunRecord], fh: TextIO) -> None:
    cells: dict[tuple[str, int], SystemMetrics] = aggregate(records)
    fields = [
        "system_id",
        "difficulty",
        "instances",
        "valid",
        "success_rate",
        "mean_score",
        "mean_solve_ms",
        "p50_solve_ms",
        "p95_solve_ms",
        "mean_verify_us",
        "total_cost_usd",
        "mean_cost_per_instance",
        "cost_per_valid_solution",
        "valid_solutions_per_dollar",
        "valid_solutions_per_second",
        "mean_attempts",
        "tokens_in",
        "tokens_out",
    ]
    writer = csv.DictWriter(fh, fieldnames=fields)
    writer.writeheader()
    for (system_id, difficulty), m in sorted(cells.items()):
        writer.writerow(
            {
                "system_id": system_id,
                "difficulty": difficulty,
                "instances": m.instances,
                "valid": m.valid,
                "success_rate": round(m.success_rate, 4),
                "mean_score": round(m.mean_score, 4),
                "mean_solve_ms": round(m.mean_solve_ms, 2),
                "p50_solve_ms": round(m.p50_solve_ms, 2),
                "p95_solve_ms": round(m.p95_solve_ms, 2),
                "mean_verify_us": round(m.mean_verify_us, 2),
                "total_cost_usd": _round_opt(m.total_cost_usd, 6),
                "mean_cost_per_instance": _round_opt(m.mean_cost_per_instance, 6),
                "cost_per_valid_solution": _round_opt(m.cost_per_valid_solution, 6),
                "valid_solutions_per_dollar": _round_opt(m.valid_solutions_per_dollar, 4),
                "valid_solutions_per_second": round(m.valid_solutions_per_second, 4),
                "mean_attempts": round(m.mean_attempts, 2),
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
            }
        )


def _record_to_row(r: RunRecord) -> dict:
    m = r.metadata
    return {
        "experiment_id": r.experiment_id,
        "challenge_id": r.challenge_id,
        "challenge_type": r.challenge_type,
        "difficulty": r.difficulty,
        "seed": r.seed,
        "system_id": r.system_id,
        "valid": r.valid,
        "score": r.score,
        "solve_wall_time_ms": round(r.solve_wall_time_ms, 3),
        "verify_time_us": r.verify_time_us,
        "error_code": r.error_code.value if r.error_code else "",
        "strategy": m.get("strategy", ""),
        "status": m.get("status", ""),
        "attempts": m.get("attempts", ""),
        "rounds": m.get("rounds", ""),
        "input_tokens": m.get("input_tokens", ""),
        "output_tokens": m.get("output_tokens", ""),
        "estimated_cost_usd": m.get("estimated_cost_usd", ""),
        "model": m.get("model", ""),
    }


__all__ = ["write_metrics_csv", "write_runs_csv", "write_runs_json"]