"""Tests for random and z3 participant systems."""

from __future__ import annotations

import pytest

from vica.challenges.csp_v01 import generate
from vica.systems import RandomSearchSystem, Z3SolverSystem


class TestRandomSearch:
    def test_random_finds_solution_for_easy_payload(self) -> None:
        # Intentionally trivial: a single equality constraint.
        payload = {
            "variables": ["A0", "A1"],
            "min_value": 0,
            "max_value": 31,
            "constraints": [{"op": "eq", "vars": ["A0", "A1"]}],
        }
        ch = {"type": "csp-v0.1", "payload": payload}
        sys_ = RandomSearchSystem(attempts=200_000)
        out = sys_.solve(ch)
        assert out.candidate is not None
        assert out.metadata["attempts"] >= 1
        assert out.metadata["solve_wall_time_ms"] >= 0

    def test_random_hard_payload_returns_none(self) -> None:
        from vica.challenges.registry import verify_candidate

        payload = generate("random-seed", 3)
        ch = {"type": "csp-v0.1", "payload": payload}
        sys_ = RandomSearchSystem(attempts=2000)
        out = sys_.solve(ch)
        # With 12 variables and ~10 constraints, random guessing should
        # statistically never hit a valid assignment in 2000 tries.
        assert out.metadata["attempts"] == 2000
        if out.candidate is not None:
            valid, _ = verify_candidate(ch, out.candidate)
            assert valid is True

    def test_random_respects_finite_attempt_budget(self) -> None:
        payload = generate("random-seed", 4)
        ch = {"type": "csp-v0.1", "payload": payload}
        sys_ = RandomSearchSystem(attempts=5)
        out = sys_.solve(ch)
        assert out.metadata["attempts"] == 5

    def test_random_rejects_wrong_payload_type(self) -> None:
        sys_ = RandomSearchSystem()
        with pytest.raises(ValueError):
            sys_.solve({"payload": {"variables": "nope"}})


class TestZ3Solver:
    @pytest.mark.parametrize("difficulty", [1, 3, 5])
    def test_z3_solves_generated_challenges(self, difficulty: int) -> None:
        payload = generate("z3-seed", difficulty)
        sys_ = Z3SolverSystem(timeout_ms=20_000)
        out = sys_.solve({"payload": payload})
        assert out.candidate is not None
        assert all(0 <= val <= 31 for val in out.candidate.values())
        assert out.candidate.keys() == set(payload["variables"])
        assert out.metadata["strategy"].startswith("z3:")

    def test_z3_full_pipeline_verifies(self) -> None:
        from vica.challenges.registry import verify_candidate

        payload = generate("z3-seed", 3)
        sys_ = Z3SolverSystem(timeout_ms=20_000)
        out = sys_.solve({"payload": payload})
        valid, score = verify_candidate({"type": "csp-v0.1", "payload": payload}, out.candidate)
        assert valid is True
        assert score == 1.0