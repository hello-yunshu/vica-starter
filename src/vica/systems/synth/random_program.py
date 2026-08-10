"""Random-program baseline for SYNTH-v0.1.

Samples DSL programs uniformly at random within the difficulty's operator
pool and keeps the first one that passes all public tests (self-checked via
the family's cheap public-tests helper). The arena verifier remains the
authority. This is the absolute floor baseline, analogous to the CSP
random-search system.
"""

from __future__ import annotations

import random
import time
from typing import Any

from vica.challenges.synth_v01.family import (
    _PARAM_POOL,  # noqa: PLC0112 — private, but this baseline lives next to the family
    DIFFICULTY_PRESETS,
    program_to_source,
    public_tests_ok,
    sample_program,
)
from vica.protocol.models import SolveOutput
from vica.protocol.serialization import stable_hash


class RandomProgramSystem:
    """Random AST generation; the floor baseline for SYNTH-v0.1."""

    system_id = "synth-random"

    def __init__(
        self,
        attempts: int = 500,
        max_seconds: float = 10.0,
        seed: int = 0,
    ) -> None:
        self.attempts = attempts
        self.max_seconds = max_seconds
        self.seed = seed

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        if isinstance(challenge, dict):
            payload: dict[str, Any] = challenge.get("payload", {})
        else:
            payload = {}
        if "public_tests" not in payload:
            raise ValueError("RandomProgramSystem expects a synth-v0.1 payload")

        difficulty = int(challenge.get("difficulty", 1) or 1)
        preset = DIFFICULTY_PRESETS.get(difficulty, DIFFICULTY_PRESETS[1])
        fn = payload.get("function", {})
        fallback_params = _PARAM_POOL.get(difficulty, ("x",))
        params = list(fn.get("params") or fallback_params)

        rng = random.Random(int(stable_hash(challenge), 16) + self.seed)
        start = time.perf_counter()

        program: str | None = None
        attempts_taken = 0
        for attempt in range(1, self.attempts + 1):
            attempts_taken = attempt
            if time.perf_counter() - start > self.max_seconds:
                break
            ast = sample_program(
                rng, params, preset.ops, preset.unary,
                preset.max_depth, preset.input_width,
            )
            if ast[0] in ("num", "var"):
                continue  # trivial; family rejects these too
            src = program_to_source(ast)
            if public_tests_ok(payload, src):
                program = src
                break

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metadata = {
            "strategy": "random-program",
            "attempts": attempts_taken,
            "solve_wall_time_ms": elapsed_ms,
        }
        candidate = {"program": program} if program is not None else None
        return SolveOutput(candidate=candidate, metadata=metadata)


__all__ = ["RandomProgramSystem"]
