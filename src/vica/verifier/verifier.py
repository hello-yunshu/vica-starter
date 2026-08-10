"""Deterministic verification service with timing."""

from __future__ import annotations

import time
from typing import Any

from vica.protocol.models import CandidateSubmission, Challenge, ErrorCode, VerificationResult


def verify_submission(
    challenge: Challenge, submission: CandidateSubmission
) -> VerificationResult:
    """Verify one submission against its challenge.

    - deterministic: same challenge + same candidate => same result
    - isolated: malformed candidates never raise
    - returns verify_time_us and a stable ErrorCode
    """
    from vica.challenges.registry import get_family

    family = get_family(challenge.type)
    if submission.challenge_id != challenge.id:
        return VerificationResult(
            challenge_id=challenge.id,
            system_id=submission.system_id,
            valid=False,
            score=0.0,
            verify_time_us=0,
            error_code=ErrorCode.WRONG_CHALLENGE,
        )

    # Pass the full challenge dict so families that need seed/difficulty
    # (e.g. SYNTH-v0.1 hidden-test regeneration) can recover them. Families
    # that only need the payload normalize internally.
    challenge_dict: dict[str, Any] = challenge.model_dump()
    candidate: Any = submission.candidate

    start = time.perf_counter_ns()
    fail: ErrorCode | None = None
    valid = False
    try:
        if hasattr(family, "failure_code"):
            fail = family.failure_code(challenge_dict, candidate)
            valid = fail is None
        else:
            valid = family.verify(challenge_dict, candidate)
            fail = None if valid else ErrorCode.INVALID_SOLUTION
    except Exception:
        valid, fail = False, ErrorCode.INTERNAL_ERROR
    finally:
        elapsed_us = int((time.perf_counter_ns() - start) // 1000)

    if not valid and fail is None:
        fail = ErrorCode.INVALID_SOLUTION

    score = family.score(challenge_dict, candidate) if valid else 0.0
    return VerificationResult(
        challenge_id=challenge.id,
        system_id=submission.system_id,
        valid=valid,
        score=score,
        verify_time_us=elapsed_us,
        error_code=fail,
    )


__all__ = ["verify_submission"]