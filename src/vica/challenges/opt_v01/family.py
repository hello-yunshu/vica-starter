"""OPT-v0.1 — optimization challenge family (single-machine total tardiness).

Design: docs/reports/opt-v0.1-design.md (design review passed).

The candidate is a job ordering (a permutation of 0..n-1). The verifier
checks that it is a valid permutation and scores it by total weighted-free
tardiness:

    C_j   = cumulative processing time of job j in the order
    T_j   = max(0, C_j - d_j)
    score = - sum_j T_j            (larger is better; 0 means zero tardiness)

1||sum T_j is NP-hard but admits an exact pseudo-polynomial / bitmask DP, so
the challenge offers a continuous score while keeping a cheap, deterministic
verifier. The verifier never judges solution quality — only legality and the
objective value.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from vica.protocol.models import ErrorCode
from vica.verifier.interfaces import EvaluationResult

TYPE_NAME = "opt-v0.1"
GENERATOR_VERSION = "0.1.0"

# Hard guard: reject absurd candidate sizes before any permutation work.
MAX_N = 64


# ------------------------------------------------------------------ difficulty

@dataclass(frozen=True)
class Preset:
    n: int
    p_max: int
    deadline_lo: float
    deadline_hi: float


DIFFICULTY_PRESETS: dict[int, Preset] = {
    1: Preset(6, 10, 0.60, 1.20),
    2: Preset(8, 20, 0.50, 1.00),
    3: Preset(10, 30, 0.40, 0.90),
    4: Preset(12, 40, 0.30, 0.80),
    5: Preset(14, 50, 0.25, 0.75),
}
MAX_DIFFICULTY = max(DIFFICULTY_PRESETS)


# ------------------------------------------------------------------ generation

def _make_rng(seed: str, difficulty: int) -> random.Random:
    return random.Random(f"{TYPE_NAME}:{GENERATOR_VERSION}:{seed}:{difficulty}")


@lru_cache(maxsize=4096)
def _generate_all(seed: str, difficulty: int) -> dict[str, Any]:
    """Deterministic generation core -> payload. Cached like SYNTH-v0.1."""
    try:
        preset = DIFFICULTY_PRESETS[difficulty]
    except KeyError:
        raise ValueError(
            f"unsupported difficulty {difficulty}; supported: {sorted(DIFFICULTY_PRESETS)}"
        ) from None

    rng = _make_rng(seed, difficulty)
    processing = [rng.randint(1, preset.p_max) for _ in range(preset.n)]
    total_p = sum(processing)
    deadlines = [
        max(0, round(rng.uniform(preset.deadline_lo, preset.deadline_hi) * total_p))
        for _ in range(preset.n)
    ]
    return {
        "n": preset.n,
        "processing": processing,
        "deadlines": deadlines,
    }


def generate(seed: str, difficulty: int) -> dict[str, Any]:
    """Public payload for (seed, difficulty). Never contains a reference solution."""
    return dict(_generate_all(seed, difficulty))


# ------------------------------------------------------------------ tardiness

def score_order(processing: list[int], deadlines: list[int], order: list[int]) -> int:
    """Total tardiness for a valid permutation (negative for the family score)."""
    t = 0
    time = 0
    for j in order:
        time += processing[j]
        if time > deadlines[j]:
            t += time - deadlines[j]
    return -t


# ------------------------------------------------------------------ family

def _resolve(payload: Any) -> tuple[list[int], list[int], int] | None:
    """Return (processing, deadlines, n) or None if the payload is unusable."""
    if not isinstance(payload, dict):
        return None
    processing = payload.get("processing")
    deadlines = payload.get("deadlines")
    n = payload.get("n")
    if not isinstance(processing, list) or not isinstance(deadlines, list):
        return None
    if not isinstance(n, int) or n <= 0 or n != len(processing) or n != len(deadlines):
        return None
    if n > MAX_N:
        return None
    return processing, deadlines, n


def _order_error(candidate: Any, n: int) -> ErrorCode | None:
    """Validate the candidate permutation; return an ErrorCode or None if valid."""
    if not isinstance(candidate, dict) or "order" not in candidate:
        return ErrorCode.INVALID_SCHEMA
    order = candidate["order"]
    if not isinstance(order, list) or len(order) != n:
        return ErrorCode.INVALID_SCHEMA
    if any(not isinstance(x, int) or isinstance(x, bool) for x in order):
        return ErrorCode.INVALID_SCHEMA
    if any(x < 0 or x >= n for x in order):
        return ErrorCode.INVALID_SCHEMA
    if len(set(order)) != n:
        return ErrorCode.INVALID_SCHEMA
    return None


class OptV01:
    """OPT-v0.1 ChallengeFamily: scheduling generator + deterministic verifier."""

    type_name = TYPE_NAME
    generator_version = GENERATOR_VERSION

    def generate(self, seed: str, difficulty: int) -> dict[str, Any]:
        return generate(seed, difficulty)

    def verify(self, challenge: Any, candidate: Any) -> bool:
        return self.evaluate(challenge, candidate).valid

    def score(self, challenge: Any, candidate: Any) -> float:
        return self.evaluate(challenge, candidate).score

    def evaluate(self, challenge: Any, candidate: Any) -> EvaluationResult:
        """Single authoritative pass: legality + objective computed exactly once."""
        payload = challenge.get("payload") if isinstance(challenge, dict) else None
        resolved = _resolve(payload)
        if resolved is None:
            return EvaluationResult(valid=False, score=0.0, error_code=ErrorCode.INVALID_SCHEMA)
        processing, deadlines, n = resolved
        code = _order_error(candidate, n)
        if code is not None:
            return EvaluationResult(valid=False, score=0.0, error_code=code)
        score = float(score_order(processing, deadlines, candidate["order"]))
        return EvaluationResult(valid=True, score=score, error_code=None)

    def failure_code(self, challenge: Any, candidate: Any) -> ErrorCode | None:
        return self.evaluate(challenge, candidate).error_code


FAMILY = OptV01()

__all__ = [
    "DIFFICULTY_PRESETS",
    "FAMILY",
    "GENERATOR_VERSION",
    "MAX_DIFFICULTY",
    "MAX_N",
    "OptV01",
    "Preset",
    "TYPE_NAME",
    "generate",
    "score_order",
]