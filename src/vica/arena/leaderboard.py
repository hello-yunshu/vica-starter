"""Leaderboard rendering (plan sections 29-30)."""

from __future__ import annotations

from vica.arena.metrics import SystemMetrics, aggregate
from vica.protocol.models import RunRecord


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
        acc.attempts.extend(cell.attempts)
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
                "total_cost_usd": round(m.total_cost_usd, 6),
                "cost_per_valid_solution": round(m.cost_per_valid_solution, 6),
                "valid_solutions_per_dollar": round(m.valid_solutions_per_dollar, 4),
                "valid_solutions_per_second": round(m.valid_solutions_per_second, 4),
                "mean_attempts": round(m.mean_attempts, 2),
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
            }
        )
    return rows


def format_leaderboard(rows: list[dict]) -> str:
    lines = [
        "VICA ARENA — Leaderboard",
        "system".ljust(18)
        + "success".rjust(8)
        + "score".rjust(8)
        + "mean_ms".rjust(9)
        + "p95_ms".rjust(9)
        + "cost_usd".rjust(10)
        + "$/sol".rjust(12)
        + "SPD".rjust(12)
        + "SPS".rjust(10),
        "-" * 96,
    ]
    for r in rows:
        lines.append(
            r["system_id"].ljust(18)
            + f"{r['success_rate']:.1%}".rjust(8)
            + f"{r['mean_score']:.3f}".rjust(8)
            + f"{r['mean_solve_ms']:.1f}".rjust(9)
            + f"{r['p95_solve_ms']:.1f}".rjust(9)
            + f"{r['total_cost_usd']:.4f}".rjust(10)
            + f"{r['cost_per_valid_solution']:.5f}".rjust(12)
            + f"{r['valid_solutions_per_dollar']:.2f}".rjust(12)
            + f"{r['valid_solutions_per_second']:.2f}".rjust(10)
        )
    return "\n".join(lines)


__all__ = ["format_leaderboard", "leaderboard_rows"]