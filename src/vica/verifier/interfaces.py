"""VICA interfaces: ChallengeFamily, SolverSystem, Verifier.

See docs/SPEC.md sections 6-7.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from vica.protocol.models import ErrorCode, SolveOutput


@runtime_checkable
class ChallengeFamily(Protocol):
    """A family of challenges with the same type and generator version.

    All three methods must be deterministic:
    - same (seed, difficulty) -> same payload
    - same (challenge, candidate) -> same result
    No remote API, no LLM, no wall-clock dependence.
    """

    type_name: str
    generator_version: str

    def generate(self, seed: str, difficulty: int) -> dict[str, Any]:
        """Generate the challenge payload for *seed* and *difficulty*."""
        ...

    def verify(self, challenge: dict[str, Any], candidate: Any) -> bool:
        """Return True iff *candidate* satisfies every requirement."""
        ...

    def score(self, challenge: dict[str, Any], candidate: Any) -> float:
        """Return a numerical score; 0.0 for invalid candidates."""
        ...


@runtime_checkable
class SolverSystem(Protocol):
    """Any participant: model, agent, algorithm, or hybrid system."""

    system_id: str

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        """Solve one challenge payload and return a candidate + metadata."""
        ...


@runtime_checkable
class Verifier(Protocol):
    """Deterministic verifier bound to one ChallengeFamily."""

    def verify(self, challenge: dict[str, Any], candidate: Any) -> bool: ...
    def score(self, challenge: dict[str, Any], candidate: Any) -> float: ...

    def failure_code(
        self, challenge: dict[str, Any], candidate: Any
    ) -> ErrorCode | None:
        """Return the ErrorCode for an invalid submission, else None."""
        ...