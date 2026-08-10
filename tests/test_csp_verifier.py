"""Tests for the CSP-v0.1 deterministic verifier (SPEC section 9.5)."""

from __future__ import annotations

import copy

import pytest

from vica.challenges.csp_v01 import FAMILY, generate, generate_with_solution
from vica.protocol.models import ErrorCode


@pytest.fixture()
def sample() -> tuple[dict, dict]:
    payload, solution = generate_with_solution("verifier-seed", 3)
    return payload, solution


def test_valid_candidate(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    assert FAMILY.verify(payload, solution) is True
    assert FAMILY.failure_code(payload, solution) is None
    assert FAMILY.score(payload, solution) == 1.0


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda s: {k: v - 1 for k, v in s.items()}, id="all-minus-one"),
        pytest.param(lambda s: {k: (v + 1) % 32 for k, v in s.items()}, id="all-plus-one"),
    ],
)
def test_perturbed_candidate_invalid(sample: tuple[dict, dict], mutation) -> None:
    payload, solution = sample
    bad = mutation(solution)
    assert FAMILY.verify(payload, bad) is False
    assert FAMILY.failure_code(payload, bad) in (
        ErrorCode.INVALID_SCHEMA,
        ErrorCode.INVALID_SOLUTION,
    )


def test_missing_variable(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    bad = {k: v for k, v in solution.items() if k != list(solution)[0]}
    assert FAMILY.verify(payload, bad) is False
    assert FAMILY.failure_code(payload, bad) == ErrorCode.INVALID_SCHEMA


def test_extra_variable(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    bad = {**solution, "ZZZ": 1}
    assert FAMILY.verify(payload, bad) is False
    assert FAMILY.failure_code(payload, bad) == ErrorCode.INVALID_SCHEMA


def test_non_integer_value(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    bad = copy.copy(solution)
    bad[list(solution)[0]] = 1.5
    assert FAMILY.verify(payload, bad) is False


def test_bool_value_rejected(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    bad = copy.copy(solution)
    bad[list(solution)[0]] = True
    assert FAMILY.verify(payload, bad) is False
    assert FAMILY.failure_code(payload, bad) == ErrorCode.INVALID_SCHEMA


def test_out_of_range_low(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    bad = copy.copy(solution)
    bad[list(solution)[0]] = -1
    assert FAMILY.verify(payload, bad) is False
    assert FAMILY.failure_code(payload, bad) == ErrorCode.INVALID_SCHEMA


def test_out_of_range_high(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    bad = copy.copy(solution)
    bad[list(solution)[0]] = 32
    assert FAMILY.verify(payload, bad) is False


def test_malformed_candidate_never_raises() -> None:
    payload = generate("malformed", 2)
    bads = [None, [], "text", 42, {"A0": "not-int"}, {}, {"A0": None}, {"A0": 0, "extra": 1}]
    for bad in bads:
        assert FAMILY.verify(payload, bad) is False  # never raises
        assert FAMILY.score(payload, bad) == 0.0


def test_constraint_semantics_each_op() -> None:
    """Verify every operator by building one constraint at a time."""
    base = {
        "variables": ["A", "B", "C"],
        "min_value": 0,
        "max_value": 31,
        "constraints": [],
    }
    # value: A=1 B=5 C=9
    v: dict = {"A": 1, "B": 5, "C": 9}

    def case(c: dict, solution: dict) -> None:
        payload = {**base, "constraints": [c]}
        assert FAMILY.verify(payload, solution) is True, c
        # generate a candidate that deterministically violates *c*
        broken = dict(solution)
        a, b = c["vars"][0], c["vars"][1]
        if c["op"] == "eq":
            broken[b] = solution[b] + 1
        elif c["op"] == "ne":
            broken[b] = solution[a]
        elif c["op"] == "lt":
            broken[b] = solution[a]  # equal, not strictly less
        elif c["op"] == "add":
            broken[a] = solution[a] + 1
        elif c["op"] == "xor":
            broken[a] = solution[a] + 1
        elif c["op"] == "mod_sum":
            broken[a] = solution[a] + 1
        elif c["op"] == "linear":
            broken[a] = solution[a] + 1
        elif c["op"] == "all_diff":
            broken[c["vars"][1]] = solution[c["vars"][0]]
        assert FAMILY.verify(payload, broken) is False, c

    case({"op": "eq", "vars": ["A", "B"]}, {"A": 1, "B": 1, "C": 9})
    case({"op": "ne", "vars": ["A", "B"]}, v)
    case({"op": "lt", "vars": ["A", "B"]}, v)
    case({"op": "add", "vars": ["A", "B"], "target": 6}, v)
    case({"op": "xor", "vars": ["A", "B"], "target": 4}, v)  # 1 ^ 5 = 4
    case({"op": "mod_sum", "vars": ["A", "B", "C"], "mod": 31, "target": 15}, v)  # 1+5+9
    case({"op": "linear", "vars": ["A", "B", "C"], "coeffs": [2, 1, 1], "target": 16}, v)  # 2+5+9
    case({"op": "all_diff", "vars": ["A", "B", "C"]}, v)

    # all_diff should fail when two values collide
    payload = {**base, "constraints": [{"op": "all_diff", "vars": ["A", "B", "C"]}]}
    assert FAMILY.verify(payload, {"A": 1, "B": 1, "C": 9}) is False


def test_unknown_operator_marked_invalid_not_crash() -> None:
    payload = {
        "variables": ["A"],
        "min_value": 0,
        "max_value": 31,
        "constraints": [{"op": "bogus", "vars": ["A"]}],
    }
    assert FAMILY.verify(payload, {"A": 1}) is False


def test_determinism_across_repeated_verification(sample: tuple[dict, dict]) -> None:
    payload, solution = sample
    results = {FAMILY.verify(payload, solution) for _ in range(50)}
    assert results == {True}
    bad = dict(solution)
    bad["A0"] = bad["A0"] + 1 if bad["A0"] < 31 else 0
    results = {FAMILY.verify(payload, bad) for _ in range(50)}
    assert results == {False}