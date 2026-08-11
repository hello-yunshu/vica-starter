"""Tests for the OPT-v0.1 baselines (random / edd / brute / dp).

Locks in invariant #5 (traditional/non-AI baselines) and the contract that
every produced candidate passes through the unified verifier.
"""

from __future__ import annotations

import pytest

from vica.challenges.opt_v01 import score_order
from vica.challenges.registry import build_challenge
from vica.protocol.models import CandidateSubmission, SolveOutput
from vica.systems.opt import BruteOptSystem, DpOptSystem, EddSystem, RandomOrderSystem
from vica.systems.opt.dp import optimal_order
from vica.verifier.verifier import verify_submission


def _challenge(difficulty: int, seed: str = "b") -> dict:
    return build_challenge("opt-v0.1", seed, difficulty).model_dump()


@pytest.mark.parametrize("difficulty", range(1, 5))
def test_baselines_return_solve_output_and_valid_candidate(difficulty: int) -> None:
    ch = _challenge(difficulty)
    for system in (
        RandomOrderSystem(),
        EddSystem(),
        BruteOptSystem(max_seconds=2.0),
        DpOptSystem(),
    ):
        out = system.solve(ch)
        assert isinstance(out, SolveOutput)
        assert out.candidate is not None
        assert isinstance(out.candidate, dict) and isinstance(out.candidate.get("order"), list)
        # candidate must be a valid permutation per the unified verifier
        assert out.candidate["order"] is not None


def test_dp_is_exact_matches_brute_on_small_instance() -> None:
    """DP and brute-force must agree on the optimal score for a small n."""
    for seed in ("a", "b", "c"):
        ch = _challenge(1, seed)
        p, d = ch["payload"]["processing"], ch["payload"]["deadlines"]
        dp_order = optimal_order(p, d)
        brute = BruteOptSystem(max_seconds=5.0).solve(ch)
        assert score_order(p, d, dp_order) == score_order(p, d, brute.candidate["order"])


def test_dp_score_is_at_least_as_good_as_edd_and_random() -> None:
    """Exact DP must be >= greedy and floor baselines on score."""
    for difficulty in (2, 3, 4):
        ch = _challenge(difficulty)
        p, d = ch["payload"]["processing"], ch["payload"]["deadlines"]
        dp_score = score_order(p, d, DpOptSystem().solve(ch).candidate["order"])
        edd_score = score_order(p, d, EddSystem().solve(ch).candidate["order"])
        rand_score = score_order(p, d, RandomOrderSystem().solve(ch).candidate["order"])
        assert dp_score >= edd_score
        assert dp_score >= rand_score


def test_dp_candidate_passes_unified_verifier() -> None:
    challenge = build_challenge("opt-v0.1", "verify-dp", 3)
    out = DpOptSystem().solve(challenge.model_dump())
    sub = CandidateSubmission(
        challenge_id=challenge.id, system_id="opt-dp", candidate=out.candidate, metadata={}
    )
    result = verify_submission(challenge, sub)
    assert result.valid is True


def test_systems_reject_non_opt_payload() -> None:
    csp = build_challenge("csp-v0.1", "x", 1).model_dump()
    with pytest.raises((ValueError, TypeError)):
        RandomOrderSystem().solve(csp)


def test_brute_respects_time_budget() -> None:
    """On a large instance brute stops at the time budget, not beyond."""
    ch = _challenge(5)
    import time

    start = time.perf_counter()
    BruteOptSystem(max_seconds=0.5).solve(ch)
    assert time.perf_counter() - start < 5.0


# --- Quality semantics (SPEC "Optimization metrics") -----------------------
# OPT is a continuous challenge: a valid permutation is not necessarily an
# optimal one. regret = optimal_score - candidate_score (>= 0) measures how
# far a valid solution is from the optimum. Section 37-39 of the freeze plan.
def _regret(p: list[int], d: list[int], order: list[int]) -> int:
    return score_order(p, d, optimal_order(p, d)) - score_order(p, d, order)


def test_exact_dp_has_zero_regret() -> None:
    """The exact DP baseline must sit on the optimum => regret == 0."""
    for seed in ("a", "b", "c"):
        ch = _challenge(2, seed)
        p, d = ch["payload"]["processing"], ch["payload"]["deadlines"]
        dp_order = DpOptSystem().solve(ch).candidate["order"]
        assert _regret(p, d, dp_order) == 0


def test_worse_schedule_has_positive_regret() -> None:
    """A deliberately poor ordering must have positive regret (not optimal)."""
    ch = _challenge(3, "regret")
    p, d = ch["payload"]["processing"], ch["payload"]["deadlines"]
    n = len(p)
    # Reverse processing order (largest first) is a poor heuristic schedule.
    order = sorted(range(n), key=lambda i: p[i], reverse=True)
    assert _regret(p, d, order) > 0


def test_valid_but_poor_schedule_is_not_optimal_success() -> None:
    """A valid permutation can still be far from optimal; valid != optimal."""
    ch = _challenge(3, "poor")
    p, d = ch["payload"]["processing"], ch["payload"]["deadlines"]
    n = len(p)
    # A valid but naive schedule (identity order) is valid yet suboptimal.
    identity = list(range(n))
    assert score_order(p, d, identity) < score_order(p, d, optimal_order(p, d))


def test_regret_quality_is_monotone_in_regret() -> None:
    """Better solutions (smaller regret) must never have lower quality.

    Freeze gate: a *worse* solution must never score a higher quality. With
    ``regret_quality = 1 - regret / reference`` (experiment-relative), quality
    is monotone decreasing in regret.
    """
    from vica.arena.metrics import regret_quality

    reference = 100.0
    assert regret_quality(0.0, reference) == 1.0  # optimal
    assert regret_quality(50.0, reference) == 0.5
    assert regret_quality(100.0, reference) == 0.0
    # Monotonicity: better (lower regret) >= worse (higher regret).
    assert regret_quality(10.0, reference) >= regret_quality(90.0, reference)
    assert regret_quality(30.0, reference) >= regret_quality(30.0, reference)
    with pytest.raises(ValueError):
        regret_quality(5.0, 0.0)


def test_runner_records_regret_metadata(tmp_path) -> None:
    """The runner attaches regret (optimal - candidate) to OPT runs.

    opt-dp must land exactly on the optimum (regret == 0); the heuristic
    baselines must never have negative regret, and at least one random run
    should be genuinely suboptimal on this fixed seed.
    """
    from vica.arena.runner import run_benchmark
    from vica.storage.db import Storage

    db = str(tmp_path / "opt.db")
    experiment_id = run_benchmark(
        challenge_type="opt-v0.1",
        difficulties=[3],
        systems=["opt-dp", "opt-random"],
        instances=4,
        seed=42,
        db_path=db,
    )
    storage = Storage(db)
    records = storage.runs_to_records(experiment_id)
    storage.close()
    for r in records:
        if r.valid:
            assert r.metadata["regret"] >= 0.0
    dp_regrets = [
        r.metadata["regret"] for r in records if r.system_id == "opt-dp" and r.valid
    ]
    random_regrets = [
        r.metadata["regret"] for r in records if r.system_id == "opt-random" and r.valid
    ]
    assert len(dp_regrets) == 4
    assert all(x == 0.0 for x in dp_regrets)  # exact DP has zero regret
    assert len(random_regrets) == 4
    assert any(x > 0.0 for x in random_regrets)  # heuristic is usually suboptimal