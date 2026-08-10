"""VICA Protocol v0.1 — core objects.

See docs/SPEC.md section 2-4 for the authoritative definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    """Result error codes defined in SPEC v0.1 section 4."""

    INVALID_SCHEMA = "INVALID_SCHEMA"
    WRONG_CHALLENGE = "WRONG_CHALLENGE"
    INVALID_SOLUTION = "INVALID_SOLUTION"
    TIMEOUT = "TIMEOUT"
    SANDBOX_ERROR = "SANDBOX_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class Challenge(BaseModel):
    """Logical representation of a challenge instance."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    generator_version: str
    seed: str
    difficulty: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class CandidateSubmission(BaseModel):
    """A system's submission for one challenge.

    metadata is self-reported and never used for correctness decisions.
    """

    model_config = ConfigDict(extra="forbid")

    challenge_id: str
    system_id: str
    candidate: Any
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """Deterministic verification output for one submission."""

    model_config = ConfigDict(extra="forbid")

    challenge_id: str
    system_id: str
    valid: bool
    score: float
    verify_time_us: int = Field(ge=0)
    error_code: ErrorCode | None = None


@dataclass
class SolveOutput:
    """Returned by every SolverSystem (SPEC v0.1 section 7)."""

    candidate: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunRecord:
    """One full benchmark run: solve + verify + measured resources."""

    experiment_id: str
    challenge_id: str
    challenge_type: str
    generator_version: str
    difficulty: int
    seed: str
    system_id: str
    candidate: Any
    valid: bool
    score: float
    solve_wall_time_ms: float
    verify_time_us: int
    error_code: ErrorCode | None = None
    metadata: dict[str, Any] = field(default_factory=dict)