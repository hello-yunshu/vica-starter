"""Deterministic verification service with timing."""

from __future__ import annotations

import time
from typing import Any

from vica.challenges.synth_v01.family import VERIFIER_SECRET_KEY
from vica.protocol.models import CandidateSubmission, Challenge, ErrorCode, VerificationResult


def verify_submission(
    challenge: Challenge,
    submission: CandidateSubmission,
    verifier_secret: str | None = None,
) -> VerificationResult:
    """Verify one submission against its challenge.

    - single authoritative evaluation: ``family.evaluate`` runs exactly once and
      its ``(valid, score, error_code)`` are reused — correctness and scoring
      are never evaluated separately.
    - isolated: malformed candidates / unknown challenge types never raise.
    - deterministic correctness: same logical (challenge, candidate) => same
      valid/score/error_code semantics. ``verify_time_us`` is telemetry and may
      vary between runs.
    - *verifier_secret* is injected into the challenge dict under an internal,
      non-model key so the family can regenerate hidden material. It is never
      part of the solver-visible Challenge.
    """
    from vica.challenges.registry import get_family
    from vica.verifier.interfaces import EvaluationResult

    if submission.challenge_id != challenge.id:
        return VerificationResult(
            challenge_id=challenge.id,
            system_id=submission.system_id,
            valid=False,
            score=0.0,
            verify_time_us=0,
            error_code=ErrorCode.WRONG_CHALLENGE,
        )

    challenge_dict: dict[str, Any] = challenge.model_dump()
    if verifier_secret:
        challenge_dict[VERIFIER_SECRET_KEY] = verifier_secret
    candidate: Any = submission.candidate

    start = time.perf_counter_ns()
    try:
        family = get_family(challenge.type)
        if hasattr(family, "evaluate"):
            result: EvaluationResult = family.evaluate(challenge_dict, candidate)
        else:  # legacy fallback: single validity pass, monotonic score
            valid = family.verify(challenge_dict, candidate)
            fail = None if valid else ErrorCode.INVALID_SOLUTION
            score = family.score(challenge_dict, candidate) if valid else 0.0
            result = EvaluationResult(valid=valid, score=score, error_code=fail)
    except Exception:
        result = EvaluationResult(False, 0.0, ErrorCode.INTERNAL_ERROR)
    finally:
        elapsed_us = int((time.perf_counter_ns() - start) // 1000)

    return VerificationResult(
        challenge_id=challenge.id,
        system_id=submission.system_id,
        valid=result.valid,
        score=result.score,
        verify_time_us=elapsed_us,
        error_code=result.error_code,
    )


__all__ = ["verify_submission"]