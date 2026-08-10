"""Aggregate benchmark metrics (docs/SPEC.md section 11, plan sections 22-27)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from vica.protocol.models import RunRecord


@dataclass
class SystemMetrics:
    """Aggregate metrics for one (system, difficulty) cell."""

    system_id: str
    difficulty: int
    instances: int = 0
    valid: int = 0
    score_sum: float = 0.0
    solve_times_ms: list[float] = field(default_factory=list)
    verify_times_us: list[int] = field(default_factory=list)
    costs_usd: list[float] = field(default_factory=list)
    attempts: list[int] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def success_rate(self) -> float:
        return self.valid / self.instances if self.instances else 0.0

    @property
    def mean_score(self) -> float:
        return self.score_sum / self.instances if self.instances else 0.0

    @property
    def mean_solve_ms(self) -> float:
        return statistics.fmean(self.solve_times_ms) if self.solve_times_ms else 0.0

    @property
    def p50_solve_ms(self) -> float:
        return statistics.median(self.solve_times_ms) if self.solve_times_ms else 0.0

    @property
    def p95_solve_ms(self) -> float:
        return _percentile(self.solve_times_ms, 95)

    @property
    def mean_verify_us(self) -> float:
        return statistics.fmean(self.verify_times_us) if self.verify_times_us else 0.0

    @property
    def total_cost_usd(self) -> float:
        return sum(self.costs_usd)

    @property
    def mean_cost_per_instance(self) -> float:
        return self.total_cost_usd / self.instances if self.instances else 0.0

    @property
    def cost_per_valid_solution(self) -> float:
        return self.total_cost_usd / self.valid if self.valid else float("inf")

    @property
    def valid_solutions_per_dollar(self) -> float:
        """SPD — the flagship metric (plan section 23)."""
        return self.valid / self.total_cost_usd if self.total_cost_usd > 0 else 0.0

    @property
    def valid_solutions_per_second(self) -> float:
        """SPS — time efficiency (plan section 24)."""
        total_s = sum(self.solve_times_ms) / 1000.0
        return self.valid / total_s if total_s > 0 else 0.0

    @property
    def mean_attempts(self) -> float:
        return statistics.fmean(self.attempts) if self.attempts else 0.0


def aggregate(records: list[RunRecord]) -> dict[tuple[str, int], SystemMetrics]:
    """Aggregate raw runs into per-(system, difficulty) metrics."""
    cells: dict[tuple[str, int], SystemMetrics] = defaultdict(
        lambda: SystemMetrics(system_id="", difficulty=0)
    )
    for r in records:
        cell = cells[(r.system_id, r.difficulty)]
        cell.system_id = r.system_id
        cell.difficulty = r.difficulty
        cell.instances += 1
        if r.valid:
            cell.valid += 1
            cell.score_sum += r.score
        cell.solve_times_ms.append(r.solve_wall_time_ms)
        cell.verify_times_us.append(r.verify_time_us)
        cost = float(r.metadata.get("estimated_cost_usd", 0.0) or 0.0)
        cell.costs_usd.append(cost)
        attempts = r.metadata.get("attempts")
        if isinstance(attempts, (int, float)):
            cell.attempts.append(int(attempts))
        cell.tokens_in += int(r.metadata.get("input_tokens", 0) or 0)
        cell.tokens_out += int(r.metadata.get("output_tokens", 0) or 0)
    return dict(cells)


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(p / 100 * len(ordered))))
    return ordered[rank - 1]


__all__ = ["SystemMetrics", "aggregate"]