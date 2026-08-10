"""Tests for the verification service (Challenge + CandidateSubmission flow)."""

from __future__ import annotations

from vica.challenges.registry import build_challenge
from vica.protocol.models import CandidateSubmission, ErrorCode
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