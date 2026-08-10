"""CSP-v0.1 — Constraint Satisfaction challenge family.

Roughly follows docs/SPEC.md section 9:

- Variables are named ``A0..An`` (SPECT-compatible, avoids collisions).
- Domains: integer ``min_value <= X <= max_value`` (default 0..31).
- Constraints are generated *backwards* from a hidden solution so the
  instance is guaranteed satisfiable.
- The hidden solution is never part of the public payload.

Determinism:
- payload = f(type_name, generator_version, seed, difficulty)
- identical seed/difficulty always produce the identical payload
- the hidden solution is only used at generation time
"""

from __future__ import annotations

import random
import string
from collections.abc import Callable
from typing import Any

from vica.protocol.models import ErrorCode
from vica.verifier.interfaces import EvaluationResult

TYPE_NAME = "csp-v0.1"
GENERATOR_VERSION = "0.1.0"

_MIN_VALUE = 0
_MAX_VALUE = 31  # variables take values in 0..31 inclusive
_EQ_PAIR_BUDGET = 64
_ALLDIFF_BUDGET = 32

# Constraint operators supported by the verifier.
OPERATORS = ("eq", "ne", "lt", "add", "xor", "mod_sum", "all_diff", "linear")

# difficulty -> (variable_count, constraint_count)
# difficulty level is a *preset parameter pack* (SPEC 10),
# to be recalibrated once experimental data exists.
DIFFICULTY_PRESETS: dict[int, tuple[int, int]] = {
    1: (8, 7),
    2: (12, 10),
    3: (16, 13),
    4: (20, 16),
    5: (24, 19),
    6: (28, 22),
    7: (32, 25),
    8: (36, 28),
    9: (40, 31),
    10: (44, 34),
}

MAX_DIFFICULTY = max(DIFFICULTY_PRESETS)


class CSPGeneratorError(ValueError):
    """Raised when an unsupported parameter combination is requested."""


def _make_rng(seed: str, difficulty: int) -> random.Random:
    """Deterministic PRNG derived from the full generation tuple."""
    return random.Random(f"{TYPE_NAME}:{GENERATOR_VERSION}:{seed}:{difficulty}")


def _variable_names(rng: random.Random, count: int) -> list[str]:
    """Generate *count* readable variable names (A0, A1, ... / B0, ...)."""
    names: list[str] = []
    letters = string.ascii_uppercase
    idx = 0
    for _ in range(count):
        letter = letters[idx // 10]
        num = idx % 10
        names.append(f"{letter}{num}")
        idx += 1
    return names


def _pick_pair(rng: random.Random, variables: list[str]) -> tuple[str, str]:
    a, b = rng.sample(variables, 2)
    return a, b


def _constraint_generators(
    rng: random.Random, variables: list[str], solution: dict[str, int]
) -> list[Callable[[], dict[str, Any] | None]]:
    """Build one generator per operator, each satisfied by *solution*.

    Each generator returns None if no satisfying instance of that operator
    exists for this hidden solution (e.g. no equal pair found).
    """

    def eq() -> dict[str, Any] | None:
        for _ in range(_EQ_PAIR_BUDGET):
            a, b = _pick_pair(rng, variables)
            if solution[a] == solution[b]:
                return {"op": "eq", "vars": [a, b]}
        return None

    def ne() -> dict[str, Any] | None:
        for _ in range(64):
            a, b = _pick_pair(rng, variables)
            if solution[a] != solution[b]:
                return {"op": "ne", "vars": [a, b]}
        # Only when every variable shares one hidden value (astronomically
        # rare, but hard to construct deterministically) — skip.
        return None

    def lt() -> dict[str, Any] | None:
        for _ in range(64):
            a, b = _pick_pair(rng, variables)
            if solution[a] < solution[b]:
                return {"op": "lt", "vars": [a, b]}
        return None

    def add() -> dict[str, Any]:
        a, b = _pick_pair(rng, variables)
        return {"op": "add", "vars": [a, b], "target": solution[a] + solution[b]}

    def xor() -> dict[str, Any]:
        a, b = _pick_pair(rng, variables)
        return {"op": "xor", "vars": [a, b], "target": solution[a] ^ solution[b]}

    def mod_sum() -> dict[str, Any]:
        mod = 31
        trio = rng.sample(variables, 3)
        total = sum(solution[v] for v in trio)
        return {"op": "mod_sum", "vars": trio, "mod": mod, "target": total % mod}

    def linear() -> dict[str, Any]:
        trio = rng.sample(variables, 3)
        coeffs = [rng.randint(1, 3) for _ in trio]
        target = sum(c * solution[v] for c, v in zip(coeffs, trio, strict=True))
        return {"op": "linear", "vars": trio, "coeffs": coeffs, "target": target}

    def all_diff() -> dict[str, Any] | None:
        for _ in range(_ALLDIFF_BUDGET):
            size = rng.randint(3, min(5, len(variables)))
            chosen = rng.sample(variables, size)
            vals = [solution[v] for v in chosen]
            if len(set(vals)) == size:
                return {"op": "all_diff", "vars": chosen}
        return None

    generators: list[Callable[[], dict[str, Any] | None]] = [
        eq,
        ne,
        lt,
        add,
        xor,
        mod_sum,
        linear,
        all_diff,
    ]
    return generators


def _build_constraints(
    rng: random.Random,
    variables: list[str],
    solution: dict[str, int],
    target_count: int,
) -> list[dict[str, Any]]:
    """Assemble exactly *target_count* constraints, each satisfied by *solution*.

    Generation is deterministic (pure RNG), so a shortfall is a property of the
    (seed, difficulty, preset) tuple, not a transient failure. We therefore
    raise a deterministic generator error instead of silently emitting a weaker
    instance that still claims the requested difficulty.
    """
    generators = _constraint_generators(rng, variables, solution)
    constraints: list[dict[str, Any]] = []
    attempts = 0
    max_attempts = target_count * 64
    while len(constraints) < target_count and attempts < max_attempts:
        attempts += 1
        gen = rng.choice(generators)
        generated = gen()
        if generated is not None:
            constraints.append(generated)
    if len(constraints) != target_count:
        raise CSPGeneratorError(
            f"csp-v0.1: only {len(constraints)}/{target_count} constraints "
            f"generated for this seed (deterministic shortfall)"
        )
    return constraints


def _generate_all(seed: str, difficulty: int) -> tuple[dict[str, Any], dict[str, int]]:
    """Shared generation core; returns (payload, hidden_solution)."""
    rng = _make_rng(seed, difficulty)
    try:
        variable_count, constraint_count = DIFFICULTY_PRESETS[difficulty]
    except KeyError:
        raise CSPGeneratorError(
            f"unsupported difficulty {difficulty}; supported: "
            f"{sorted(DIFFICULTY_PRESETS)}"
        ) from None

    variables = _variable_names(rng, variable_count)
    solution = {v: rng.randint(_MIN_VALUE, _MAX_VALUE) for v in variables}
    constraints = _build_constraints(rng, variables, solution, constraint_count)

    payload = {
        "variables": variables,
        "min_value": _MIN_VALUE,
        "max_value": _MAX_VALUE,
        "constraints": constraints,
    }
    return payload, solution


def generate(seed: str, difficulty: int) -> dict[str, Any]:
    """Generate the public CSP-v0.1 payload for (seed, difficulty).

    The payload contains no reference to the hidden solution.
    """
    payload, _ = _generate_all(seed, difficulty)
    return payload


def generate_with_solution(seed: str, difficulty: int) -> tuple[dict[str, Any], dict[str, int]]:
    """Generate the payload plus its hidden solution (for tests/calibration only).

    The hidden solution is never serialized into a public challenge.
    """
    return _generate_all(seed, difficulty)


class CSPV01:
    """CSP-v0.1 ChallengeFamily: generator + deterministic verifier."""

    type_name = TYPE_NAME
    generator_version = GENERATOR_VERSION

    # ---------------------------------------------------------------- generate

    def generate(self, seed: str, difficulty: int) -> dict[str, Any]:
        return generate(seed, difficulty)

    # ---------------------------------------------------------------- verifier

    def verify(self, payload: dict[str, Any], candidate: Any) -> bool:
        return self.evaluate(payload, candidate).valid

    def score(self, payload: dict[str, Any], candidate: Any) -> float:
        return self.evaluate(payload, candidate).score

    def evaluate(self, payload: dict[str, Any], candidate: Any) -> EvaluationResult:
        """Single authoritative pass: validity + score computed exactly once."""
        fail = self.failure_code(payload, candidate)
        valid = fail is None
        return EvaluationResult(valid=valid, score=1.0 if valid else 0.0, error_code=fail)

    def failure_code(self, payload: dict[str, Any], candidate: Any) -> ErrorCode | None:
        if not isinstance(payload, dict):
            return ErrorCode.INVALID_SCHEMA
        # Accept either a bare payload or a full challenge dict (the verifier
        # service passes the full challenge; legacy callers pass the payload).
        if "payload" in payload and "constraints" not in payload:
            inner = payload.get("payload")
            if not isinstance(inner, dict):
                return ErrorCode.INVALID_SCHEMA
            payload = inner
        if not isinstance(candidate, dict):
            return ErrorCode.INVALID_SCHEMA

        try:
            variables = list(payload["variables"])
            min_v = int(payload["min_value"])
            max_v = int(payload["max_value"])
            constraints = list(payload["constraints"])
        except (KeyError, TypeError, ValueError):
            return ErrorCode.INVALID_SCHEMA

        # Exact variable set: no missing, no extra (SPEC 9.5).
        if set(candidate) != set(variables):
            return ErrorCode.INVALID_SCHEMA

        # Integer values within the domain. bool is rejected (int subclass).
        for var in variables:
            value = candidate[var]
            if isinstance(value, bool) or not isinstance(value, int):
                return ErrorCode.INVALID_SCHEMA
            if value < min_v or value > max_v:
                return ErrorCode.INVALID_SCHEMA

        # Constraint semantics. Any malformed constraint entry or a violated
        # constraint invalidates the candidate.
        try:
            for c in constraints:
                if not self._constraint_holds(c, candidate):
                    return ErrorCode.INVALID_SOLUTION
        except (KeyError, TypeError, ValueError):
            return ErrorCode.INVALID_SCHEMA

        return None

    @staticmethod
    def _constraint_holds(c: dict[str, Any], values: dict[str, int]) -> bool:
        op = c["op"]
        vars_ = [str(v) for v in c["vars"]]
        if op == "eq":
            return values[vars_[0]] == values[vars_[1]]
        if op == "ne":
            return values[vars_[0]] != values[vars_[1]]
        if op == "lt":
            return values[vars_[0]] < values[vars_[1]]
        if op == "add":
            return values[vars_[0]] + values[vars_[1]] == int(c["target"])
        if op == "xor":
            return values[vars_[0]] ^ values[vars_[1]] == int(c["target"])
        if op == "mod_sum":
            mod = int(c.get("mod", 31))
            total = sum(values[v] for v in vars_)
            return total % mod == int(c["target"])
        if op == "linear":
            coeffs = [int(x) for x in c["coeffs"]]
            total = sum(co * values[v] for co, v in zip(coeffs, vars_, strict=True))
            return total == int(c["target"])
        if op == "all_diff":
            vals = [values[v] for v in vars_]
            return len(vals) == len(set(vals))
        raise ValueError(f"unknown constraint operator: {op!r}")


FAMILY = CSPV01()