"""v0.2 Evaluation protocol — core value objects.

This module defines the portable artifacts of the Benchmark Research &
External Evaluation milestone (docs/BENCHMARK_METHODOLOGY.md):

- Evaluation Bundle  (public + private)
- Submission Bundle (external solver output, untrusted)
- Result Bundle     (portable, reverifiable research artifact)

The report-level failure taxonomy intentionally differs from the protocol
``ErrorCode``: protocol codes describe a single authoritative verification
outcome, while the report taxonomy separates evaluator / infrastructure /
solver outcomes so a benchmark report can distinguish "wrong answer" from
"no answer" from "the evaluation itself was misconfigured".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from vica.protocol.models import ErrorCode

# Version of the Evaluation / Submission / Result bundle formats. Independent
# of the VICA software version, the Protocol version, and each challenge
# generator version (docs/BENCHMARK_METHODOLOGY.md "Version concepts").
BUNDLE_FORMAT_VERSION = "1"
SUBMISSION_BUNDLE_VERSION = "1"
RESULT_BUNDLE_VERSION = "1"


class ReportStatus(StrEnum):
    """Report-level failure taxonomy (docs/BENCHMARK_METHODOLOGY.md).

    This is the *reporting* layer. Multiple protocol ``ErrorCode`` values may
    map to one report status, and the render keeps evaluator errors separate
    from solver outcomes.
    """

    VALID = "valid"
    INVALID_SOLUTION = "invalid_solution"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    PROVIDER_ERROR = "provider_error"
    PARSE_ERROR = "parse_error"
    NO_CANDIDATE = "no_candidate"
    NO_SUBMISSION = "no_submission"
    SANDBOX_ERROR = "sandbox_error"
    INTERNAL_ERROR = "internal_error"
    UNSUPPORTED = "unsupported"


class EvaluationFailure(RuntimeError):
    """An evaluation-level configuration / integrity failure.

    Raised for wrong verifier material, corrupt private bundle, manifest hash
    mismatch, unknown generator version, etc. These are **not** solver
    outcomes and must never be recorded as per-instance solver failures
    (docs/BENCHMARK_METHODOLOGY.md "Evaluation-level vs Solver-level errors").
    """


@dataclass
class ResultRecord:
    """One authoritative verification result inside a Result Bundle.

    ``status`` is the report-level taxonomy; ``error_code`` is the protocol
    ``ErrorCode``. ``solve_wall_time_ms`` / ``verify_time_us`` are telemetry.
    """

    challenge_id: str
    challenge_type: str
    generator_version: str
    difficulty: int
    seed: str
    system_id: str
    valid: bool
    score: float
    status: ReportStatus
    error_code: ErrorCode | None = None
    solve_wall_time_ms: float = 0.0
    verify_time_us: int = 0
    candidate: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


def to_result_record(
    challenge_id: str,
    challenge_type: str,
    generator_version: str,
    difficulty: int,
    seed: str,
    system_id: str,
    *,
    valid: bool,
    score: float,
    error_code: ErrorCode | None,
    solve_wall_time_ms: float = 0.0,
    verify_time_us: int = 0,
    candidate: Any = None,
    metadata: dict[str, Any] | None = None,
    status: ReportStatus | None = None,
) -> ResultRecord:
    """Build a ResultRecord, mapping a protocol error to a report status.

    ``status`` overrides the default mapping for cases that have no protocol
    ``error_code`` but a distinct report status — most importantly
    ``NO_SUBMISSION`` (a missing challenge must never be conflated with a
    wrong answer).
    """
    if status is None:
        status = _status_for(error_code, valid)
    return ResultRecord(
        challenge_id=challenge_id,
        challenge_type=challenge_type,
        generator_version=generator_version,
        difficulty=difficulty,
        seed=seed,
        system_id=system_id,
        valid=valid,
        score=score,
        status=status,
        error_code=error_code,
        solve_wall_time_ms=solve_wall_time_ms,
        verify_time_us=verify_time_us,
        candidate=candidate,
        metadata=metadata or {},
    )


def _status_for(error_code: ErrorCode | None, valid: bool) -> ReportStatus:
    if valid and error_code is None:
        return ReportStatus.VALID
    if error_code is None:
        return ReportStatus.VALID
    mapping: dict[ErrorCode, ReportStatus] = {
        ErrorCode.INVALID_SCHEMA: ReportStatus.PARSE_ERROR,
        ErrorCode.WRONG_CHALLENGE: ReportStatus.NO_CANDIDATE,
        ErrorCode.INVALID_SOLUTION: ReportStatus.INVALID_SOLUTION,
        ErrorCode.TIMEOUT: ReportStatus.TIMEOUT,
        ErrorCode.SANDBOX_ERROR: ReportStatus.SANDBOX_ERROR,
        ErrorCode.INTERNAL_ERROR: ReportStatus.INTERNAL_ERROR,
    }
    return mapping.get(error_code, ReportStatus.INTERNAL_ERROR)


__all__ = [
    "BUNDLE_FORMAT_VERSION",
    "EvaluationFailure",
    "ReportStatus",
    "RESULT_BUNDLE_VERSION",
    "ResultRecord",
    "SUBMISSION_BUNDLE_VERSION",
    "to_result_record",
]