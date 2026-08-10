"""Random baseline system.

Samples assignments uniformly at random from the CSP domain until a valid
candidate is found or the attempt/elapsed-time budget is exhausted.

The system itself uses the public deterministic verifier to detect a valid
sample. The arena runner still performs the authoritative verification.
"""

from __future__ import annotations

import random
import time
from typing import Any

from vica.protocol.models import SolveOutput
from vica.protocol.serialization import stable_hash


class RandomSearchSystem:
    """Pure random guessing; the absolute floor baseline."""

    system_id = "random"

    def __init__(self, attempts: int = 2000, max_seconds: float = 10.0, seed: int = 0) -> None:
        self.attempts = attempts
        self.max_seconds = max_seconds
        self.seed = seed

    def config(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "max_seconds": self.max_seconds,
            "seed": self.seed,
        }

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        from vica.challenges.registry import verify_candidate

        payload: dict[str, Any] = challenge.get("payload", {})
        variables = payload.get("variables")
        if (
            not isinstance(payload, dict)
            or not isinstance(variables, list)
            or not variables
            or "min_value" not in payload
            or "max_value" not in payload
        ):
            raise ValueError("RandomSearchSystem expects a csp-style challenge payload")

        min_v = int(payload["min_value"])
        max_v = int(payload["max_value"])

        # Process-stable seed derived from the challenge itself + fixed offset.
        rng = random.Random(int(stable_hash(challenge), 16) + self.seed)
        start = time.perf_counter()

        candidate: dict[str, int] | None = None
        attempts_taken = 0
        for attempt in range(1, self.attempts + 1):
            attempts_taken = attempt
            if time.perf_counter() - start > self.max_seconds:
                break
            sampled = {v: rng.randint(min_v, max_v) for v in variables}
            valid, _ = verify_candidate(challenge=challenge, candidate=sampled)
            if valid:
                candidate = sampled
                break

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metadata = {
            "strategy": "uniform-random",
            "attempts": attempts_taken,
            "solve_wall_time_ms": elapsed_ms,
        }
        return SolveOutput(candidate=candidate, metadata=metadata)


__all__ = ["RandomSearchSystem"]