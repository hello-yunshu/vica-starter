"""Aggregate benchmark metrics (docs/SPEC.md section 11, plan sections 22-27)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from vica.protocol.models import RunRecord


@dataclass
class SystemMetrics:
    """Aggregate metrics for one (system, difficulty) cell.

    Cost semantics (SPEC "Cost semantics"): ``estimated_cost_usd`` is allowed
    to be UNKNOWN (None). Cost-derived metrics therefore return ``None`` (N/A)
    whenever any instance in the cell has an unknown cost — they must never be
    silently reported as 0 to avoid implying the runs were free.
    """

    system_id: str
    difficulty: int
    instances: int = 0
    valid: int = 0
    score_sum: float = 0.0
    solve_times_ms: list[float] = field(default_factory=list)
    verify_times_us: list[int] = field(default_factory=list)
    costs_usd: list[float] = field(default_factory=list)
    cost_unknown_instances: int = 0
    attempts: list[int] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    regrets: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.valid / self.instances if self.instances else 0.0

    @property
    def mean_score(self) -> float:
        return self.score_sum / self.instances if self.instances else 0.0

    @property
    def mean_regret(self) -> float | None:
        """Mean OPT regret over valid runs, or ``None`` when no regret data.

        Regret = optimal_score - candidate_score (>= 0; 0 is optimal); it is
        attached to valid OPT runs only. ``None`` means the cell has no OPT
        regret information — surfaced as N/A, never as a misleading 0.
        """
        if not self.regrets:
            return None
        return statistics.fmean(self.regrets)

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
    def cost_known(self) -> bool:
        """True when every instance's cost is known (no UNKNOWN costs)."""
        return self.cost_unknown_instances == 0

    @property
    def total_cost_usd(self) -> float | None:
        """Known total cost, or ``None`` when any instance has UNKNOWN cost."""
        if not self.cost_known:
            return None
        return sum(self.costs_usd)

    @property
    def mean_cost_per_instance(self) -> float | None:
        if not self.cost_known or not self.instances:
            return None
        return sum(self.costs_usd) / self.instances

    @property
    def cost_per_valid_solution(self) -> float | None:
        if not self.cost_known or not self.valid:
            return None
        return sum(self.costs_usd) / self.valid

    @property
    def valid_solutions_per_dollar(self) -> float | None:
        """SPD — the flagship metric (plan section 23). N/A when cost unknown."""
        if not self.cost_known:
            return None
        total = sum(self.costs_usd)
        if total <= 0:
            # Known-but-zero total cost: division is undefined, do not claim 0.
            return None
        return self.valid / total

    @property
    def valid_solutions_per_second(self) -> float:
        """SPS — time efficiency (plan section 24)."""
        total_s = sum(self.solve_times_ms) / 1000.0
        return self.valid / total_s if total_s > 0 else 0.0

    @property
    def mean_attempts(self) -> float:
        return statistics.fmean(self.attempts) if self.attempts else 0.0


def regret_quality(regret: float, reference: float) -> float:
    """Experiment-relative normalized quality: ``1 - regret / reference``.

    ``reference`` is the worst regret observed in the comparison set (e.g. the
    worst run of any system in the same experiment). Quality is 1.0 for the
    optimal solution (regret 0) and 0.0 at the reference regret, monotone
    decreasing in regret. This is explicitly *experiment-relative*: it is not
    an absolute quality bound and must be documented as such. Raises
    ``ValueError`` when ``reference`` is not positive.
    """
    if reference <= 0:
        raise ValueError("regret_quality: reference regret must be > 0")
    return max(0.0, min(1.0, 1.0 - regret / reference))


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
        cost = r.metadata.get("estimated_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            cell.costs_usd.append(float(cost))
        else:
            # Absent or None => cost is UNKNOWN, not zero (SPEC "Cost semantics").
            cell.cost_unknown_instances += 1
        attempts = r.metadata.get("attempts")
        if isinstance(attempts, (int, float)):
            cell.attempts.append(int(attempts))
        regret = r.metadata.get("regret")
        if isinstance(regret, (int, float)) and not isinstance(regret, bool):
            cell.regrets.append(float(regret))
        cell.tokens_in += int(r.metadata.get("input_tokens", 0) or 0)
        cell.tokens_out += int(r.metadata.get("output_tokens", 0) or 0)
    return dict(cells)


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(p / 100 * len(ordered))))
    return ordered[rank - 1]


__all__ = ["SystemMetrics", "aggregate", "regret_quality"]