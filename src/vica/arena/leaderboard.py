"""Leaderboard rendering (plan sections 29-30)."""

from __future__ import annotations

from vica.arena.metrics import SystemMetrics, aggregate
from vica.protocol.models import RunRecord


def _round_opt(value: float | None, ndigits: int) -> float | None:
    """Round a metric, preserving ``None`` (UNKNOWN cost) as N/A."""
    return round(value, ndigits) if value is not None else None


def leaderboard_rows(records: list[RunRecord]) -> list[dict]:
    """Per-system aggregates across all difficulties of one experiment."""
    cells = aggregate(records)
    per_system: dict[str, SystemMetrics] = {}
    for (system_id, _), cell in cells.items():
        acc = per_system.setdefault(
            system_id, SystemMetrics(system_id=system_id, difficulty=0)
        )
        acc.instances += cell.instances
        acc.valid += cell.valid
        acc.score_sum += cell.score_sum
        acc.solve_times_ms.extend(cell.solve_times_ms)
        acc.verify_times_us.extend(cell.verify_times_us)
        acc.costs_usd.extend(cell.costs_usd)
        acc.cost_unknown_instances += cell.cost_unknown_instances
        acc.attempts.extend(cell.attempts)
        acc.regrets.extend(cell.regrets)
        acc.tokens_in += cell.tokens_in
        acc.tokens_out += cell.tokens_out

    rows = []
    for system_id, m in sorted(per_system.items()):
        rows.append(
            {
                "system_id": system_id,
                "instances": m.instances,
                "valid": m.valid,
                "success_rate": round(m.success_rate, 4),
                "mean_score": round(m.mean_score, 4),
                "mean_solve_ms": round(m.mean_solve_ms, 2),
                "p50_solve_ms": round(m.p50_solve_ms, 2),
                "p95_solve_ms": round(m.p95_solve_ms, 2),
                "mean_verify_us": round(m.mean_verify_us, 2),
                "total_cost_usd": _round_opt(m.total_cost_usd, 6),
                "cost_per_valid_solution": _round_opt(m.cost_per_valid_solution, 6),
                "valid_solutions_per_dollar": _round_opt(m.valid_solutions_per_dollar, 4),
                "valid_solutions_per_second": round(m.valid_solutions_per_second, 4),
                "mean_regret": _round_opt(m.mean_regret, 4),
                "mean_attempts": round(m.mean_attempts, 2),
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
            }
        )
    return rows


def format_optional_metric(value: float | None, spec: str) -> str:
    """Format a metric, rendering UNKNOWN cost (``None``) as ``N/A``.

    Cost-derived metrics are ``None`` when any instance's cost is unknown
    (SPEC "Cost semantics"); they must surface as N/A, never crash the renderer
    or be printed as a misleading 0/blank. Shared by the leaderboard and the
    ``vica report`` CLI so both render identically.
    """
    if value is None:
        return "N/A"
    return f"{value:{spec}}"


def _fmt(value: float | None, spec: str) -> str:
    """Backwards-compatible alias of :func:`format_optional_metric`."""
    return format_optional_metric(value, spec)


def format_leaderboard(rows: list[dict]) -> str:
    lines = [
        "VICA ARENA — Leaderboard",
        "system".ljust(18)
        + "success".rjust(8)
        + "score".rjust(8)
        + "mean_ms".rjust(9)
        + "p95_ms".rjust(9)
        + "regret".rjust(9)
        + "cost_usd".rjust(10)
        + "$/sol".rjust(12)
        + "SPD".rjust(12)
        + "SPS".rjust(10),
        "-" * 105,
    ]
    for r in rows:
        lines.append(
            r["system_id"].ljust(18)
            + f"{r['success_rate']:.1%}".rjust(8)
            + f"{r['mean_score']:.3f}".rjust(8)
            + f"{r['mean_solve_ms']:.1f}".rjust(9)
            + f"{r['p95_solve_ms']:.1f}".rjust(9)
            + _fmt(r["mean_regret"], ".3f").rjust(9)
            + _fmt(r["total_cost_usd"], ".4f").rjust(10)
            + _fmt(r["cost_per_valid_solution"], ".5f").rjust(12)
            + _fmt(r["valid_solutions_per_dollar"], ".2f").rjust(12)
            + f"{r['valid_solutions_per_second']:.2f}".rjust(10)
        )
    return "\n".join(lines)


__all__ = ["format_leaderboard", "format_optional_metric", "leaderboard_rows"]