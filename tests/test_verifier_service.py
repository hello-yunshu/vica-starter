"""Tests for the verification service (Challenge + CandidateSubmission flow)."""

from __future__ import annotations

import pytest

from vica.challenges.registry import build_challenge, register
from vica.protocol.models import CandidateSubmission, ErrorCode
from vica.verifier.interfaces import EvaluationResult
from vica.verifier.verifier import verify_submission


def test_valid_submission() -> None:
    challenge = build_challenge("csp-v0.1", "vs-seed", 2)
    from vica.challenges.csp_v01 import generate_with_solution

    _, solution = generate_with_solution("vs-seed", 2)
    submission = CandidateSubmission(
        challenge_id=challenge.id,
        system_id="test",
        candidate=solution,
        metadata={},
    )
    result = verify_submission(challenge, submission)
    assert result.valid is True
    assert result.score == 1.0
    assert result.error_code is None
    assert result.verify_time_us >= 0


def test_wrong_challenge_id() -> None:
    challenge = build_challenge("csp-v0.1", "vs-seed", 2)
    submission = CandidateSubmission(
        challenge_id="some-other-id",
        system_id="test",
        candidate={},
        metadata={},
    )
    result = verify_submission(challenge, submission)
    assert result.valid is False
    assert result.error_code == ErrorCode.WRONG_CHALLENGE


def test_malformed_candidate_yields_error_code() -> None:
    challenge = build_challenge("csp-v0.1", "vs-seed", 2)
    submission = CandidateSubmission(
        challenge_id=challenge.id,
        system_id="test",
        candidate="not-a-dict",
        metadata={},
    )
    result = verify_submission(challenge, submission)
    assert result.valid is False
    assert result.error_code is not None


def test_deterministic_across_calls() -> None:
    from vica.challenges.csp_v01 import generate_with_solution

    challenge = build_challenge("csp-v0.1", "vs-seed", 2)
    _, solution = generate_with_solution("vs-seed", 2)
    submission = CandidateSubmission(
        challenge_id=challenge.id, system_id="test", candidate=solution, metadata={}
    )
    r1 = verify_submission(challenge, submission)
    r2 = verify_submission(challenge, submission)
    assert r1.valid is True and r2.valid is True
    assert r1.error_code == r2.error_code


# ------------------------------------------- P0-3: single authoritative evaluation


class _CountingFamily:
    """Poor-man's ChallengeFamily that counts how often evaluate() is called."""

    type_name = "test-counting-v0.1"
    generator_version = "0.1.0"
    calls = 0

    def generate(self, seed: str, difficulty: int) -> dict:
        return {"seed": seed, "difficulty": difficulty}

    def verify(self, challenge: dict, candidate: object) -> bool:
        return candidate is not None

    def score(self, challenge: dict, candidate: object) -> float:
        return 1.0 if candidate is not None else 0.0

    def evaluate(self, challenge: dict, candidate: object) -> EvaluationResult:
        self.calls += 1
        valid = candidate is not None
        return EvaluationResult(valid=valid, score=1.0 if valid else 0.0)

    def failure_code(self, challenge: dict, candidate: object) -> ErrorCode | None:
        return None if candidate is not None else ErrorCode.INVALID_SOLUTION


def test_evaluate_invoked_once_per_submission() -> None:
    """verify_submission must call family.evaluate exactly once (no double eval)."""
    family = _CountingFamily()
    register(family)
    try:
        challenge = build_challenge(family.type_name, "ct-seed", 1)
        submission = CandidateSubmission(
            challenge_id=challenge.id, system_id="t", candidate="x", metadata={}
        )
        family.calls = 0
        result = verify_submission(challenge, submission)
        assert family.calls == 1
        assert result.valid is True
    finally:
        from vica.challenges import registry as _reg

        _reg._REGISTRY.pop(family.type_name, None)


def test_unknown_challenge_type_does_not_crash() -> None:
    """An unregistered challenge type must not crash the arena."""
    from vica.protocol.models import Challenge

    challenge = Challenge(
        id="unknown-id",
        type="no-such-family-v0.1",
        generator_version="0.1.0",
        seed="s",
        difficulty=1,
        payload={},
    )
    submission = CandidateSubmission(
        challenge_id=challenge.id, system_id="t", candidate={}, metadata={}
    )
    result = verify_submission(challenge, submission)
    assert result.valid is False
    from vica.challenges.registry import get_family as _gf

    with pytest.raises(ValueError):
        _gf(challenge.type)


def test_score_exception_does_not_crash_arena() -> None:
    """A family that raises inside evaluate maps to INTERNAL_ERROR, not a crash."""
    family = _CountingFamily()
    orig_evaluate = family.evaluate

    def boom(challenge: dict, candidate: object) -> EvaluationResult:
        raise RuntimeError("score exploded")

    family.evaluate = boom  # type: ignore[method-assign]
    register(family)
    try:
        challenge = build_challenge(family.type_name, "boom-seed", 1)
        submission = CandidateSubmission(
            challenge_id=challenge.id, system_id="t", candidate="x", metadata={}
        )
        result = verify_submission(challenge, submission)
        assert result.valid is False
        assert result.error_code == ErrorCode.INTERNAL_ERROR
    finally:
        from vica.challenges import registry as _reg

        _reg._REGISTRY.pop(family.type_name, None)
        family.evaluate = orig_evaluate


def test_timing_is_excluded_from_deterministic_equality() -> None:
    """Correctness/score/error are deterministic; verify_time_us is telemetry."""
    challenge = build_challenge("csp-v0.1", "vs-seed", 2)
    from vica.challenges.csp_v01 import generate_with_solution

    _, solution = generate_with_solution("vs-seed", 2)
    submission = CandidateSubmission(
        challenge_id=challenge.id, system_id="test", candidate=solution, metadata={}
    )
    results = [verify_submission(challenge, submission) for _ in range(3)]
    semantics = {(r.valid, r.score, r.error_code) for r in results}
    assert len(semantics) == 1  # logical result identical across runs
    # timing may vary; at minimum it is a non-negative measurement, not semantics
    assert all(r.verify_time_us >= 0 for r in results)