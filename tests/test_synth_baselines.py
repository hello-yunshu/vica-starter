"""Tests for the SYNTH-v0.1 non-AI baselines (random-program, brute-force).

These lock in invariant #5 (every challenge has a traditional/non-AI
baseline) and the budget contract: systems never crash, always return a
SolveOutput, and respect the time/attempt caps.
"""

from __future__ import annotations

import pytest

from vica.challenges.registry import build_challenge
from vica.protocol.models import SolveOutput
from vica.systems.synth import BruteForceSynthSystem, RandomProgramSystem


@pytest.fixture()
def challenge_d1() -> dict:
    return build_challenge("synth-v0.1", "baseline-d1", 1).model_dump()


@pytest.fixture()
def challenge_d3() -> dict:
    return build_challenge("synth-v0.1", "baseline-d3", 3).model_dump()


def test_random_returns_solve_output(challenge_d1: dict) -> None:
    out = RandomProgramSystem(attempts=50, max_seconds=2.0).solve(challenge_d1)
    assert isinstance(out, SolveOutput)
    assert out.metadata["strategy"] == "random-program"
    assert out.metadata["attempts"] >= 1
    # candidate is either a valid program dict or None — never something else
    assert out.candidate is None or (
        isinstance(out.candidate, dict) and isinstance(out.candidate.get("program"), str)
    )


def test_brute_returns_solve_output(challenge_d1: dict) -> None:
    out = BruteForceSynthSystem(
        max_nodes=9, max_candidates=20_000, max_seconds=5.0,
    ).solve(challenge_d1)
    assert isinstance(out, SolveOutput)
    assert out.metadata["strategy"] == "brute-force-enum"
    assert out.metadata["candidates_checked"] >= 1


def test_brute_solves_low_difficulty(challenge_d1: dict) -> None:
    """Brute-force must reliably solve d=1 (small linear targets)."""
    solved = 0
    for i in range(6):
        ch = build_challenge("synth-v0.1", f"brute-d1-{i}", 1).model_dump()
        out = BruteForceSynthSystem(max_nodes=11, max_candidates=100_000, max_seconds=8.0).solve(ch)
        if out.candidate is not None:
            solved += 1
    assert solved >= 5  # near-certain on d=1


def test_systems_reject_non_synth_payload() -> None:
    from vica.challenges.registry import build_challenge

    csp = build_challenge("csp-v0.1", "x", 1).model_dump()
    with pytest.raises(ValueError):
        RandomProgramSystem().solve(csp)
    with pytest.raises(ValueError):
        BruteForceSynthSystem().solve(csp)


def test_random_respects_attempt_budget(challenge_d3: dict) -> None:
    sys = RandomProgramSystem(attempts=10, max_seconds=2.0)
    out = sys.solve(challenge_d3)
    assert out.metadata["attempts"] == 10


def test_brute_respects_candidate_cap(challenge_d3: dict) -> None:
    """On a hard target, brute-force stops at the candidate cap, not beyond."""
    sys = BruteForceSynthSystem(max_nodes=7, max_candidates=500, max_seconds=10.0)
    out = sys.solve(challenge_d3)
    assert out.metadata["candidates_checked"] <= 600  # small overshoot per loop iter
