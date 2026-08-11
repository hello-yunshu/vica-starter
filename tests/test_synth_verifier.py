"""Tests for the SYNTH-v0.1 deterministic verifier and DSL sandbox.

Covers design doc sections 4 (Deterministic Verifier), 5 (Sandbox), and the
DoD: malformed candidate never crashes, sandbox guards reject resource bombs.
"""

from __future__ import annotations

import pytest

from vica.challenges.synth_v01 import (
    FAMILY,
    TYPE_NAME,
    VERIFIER_SECRET_KEY,
    generate_with_solution,
)
from vica.challenges.synth_v01.family import (
    MAX_EVAL_STEPS,
    MAX_INT_BITS,
    MAX_PARSE_DEPTH,
    MAX_TOKENS,
    ParseError,
    SandboxLimit,
    eval_program,
    parse_program,
    program_to_source,
)
from vica.protocol.models import ErrorCode

TEST_SECRET = "test-verifier-secret"


@pytest.fixture()
def challenge() -> tuple[dict, dict]:
    payload, sol = generate_with_solution("verifier-seed", 3, TEST_SECRET)
    full = {
        "type": TYPE_NAME,
        "seed": "verifier-seed",
        "difficulty": 3,
        "payload": payload,
        VERIFIER_SECRET_KEY: TEST_SECRET,
    }
    return full, sol


# ------------------------------------------------------------------ valid path

def test_target_program_verifies(challenge: tuple[dict, dict]) -> None:
    full, sol = challenge
    cand = {"program": sol["target_program"]}
    assert FAMILY.verify(full, cand) is True
    assert FAMILY.failure_code(full, cand) is None
    assert FAMILY.score(full, cand) == 1.0


def test_round_trips_through_printer(challenge: tuple[dict, dict]) -> None:
    full, sol = challenge
    node = parse_program(sol["target_program"])
    rt = program_to_source(node)
    # textual round-trip reproduces the canonical source
    assert rt == sol["target_program"]
    # and re-parses to the same AST
    assert parse_program(rt) == node
    assert FAMILY.verify(full, {"program": rt}) is True


# ------------------------------------------------------------------ invalid programs

def test_wrong_output_invalid(challenge: tuple[dict, dict]) -> None:
    full, _ = challenge
    # a program that returns the wrong value on at least one test
    assert FAMILY.verify(full, {"program": "x + 1 - 1 - 1"}) is False
    assert FAMILY.failure_code(full, {"program": "x + 1 - 1 - 1"}) == ErrorCode.INVALID_SOLUTION


def test_div_by_zero_is_invalid_not_crash(challenge: tuple[dict, dict]) -> None:
    full, _ = challenge
    fc = FAMILY.failure_code(full, {"program": "x // (x - x)"})
    assert fc in (ErrorCode.INVALID_SCHEMA, ErrorCode.SANDBOX_ERROR)


def test_malformed_candidate_never_raises(challenge: tuple[dict, dict]) -> None:
    full, _ = challenge
    bads = [
        None,
        [],
        "text",
        42,
        {},
        {"program": 5},
        {"program": None},
        {"program": ""},
        {"program": "1 +"},
        {"program": "1 + )"},
        {"program": "@#$"},
        {"program": "f(x)"},
        {"program": "1 2"},
    ]
    for bad in bads:
        assert FAMILY.verify(full, bad) is False
        assert FAMILY.score(full, bad) == 0.0
        assert FAMILY.failure_code(full, bad) is not None


def test_unknown_variable_invalid(challenge: tuple[dict, dict]) -> None:
    full, _ = challenge
    # d=3 uses x,y; referencing z (only valid at d=5) is an eval error
    fc = FAMILY.failure_code(full, {"program": "z + 1"})
    assert fc in (ErrorCode.INVALID_SCHEMA, ErrorCode.INVALID_SOLUTION)


# ------------------------------------------------------------------ code-size budget

def test_code_size_budget_enforced(challenge: tuple[dict, dict]) -> None:
    full, _ = challenge
    # d=3 preset code_size=200; build a program clearly over budget
    big = " + ".join(["x"] * 250)
    fc = FAMILY.failure_code(full, {"program": big})
    assert fc == ErrorCode.INVALID_SCHEMA


# ------------------------------------------------------------------ sandbox guards

def test_parse_depth_guard() -> None:
    # deeply nested parenthesization past MAX_PARSE_DEPTH
    depth = MAX_PARSE_DEPTH + 10
    src = "(" * depth + "x" + ")" * depth
    with pytest.raises(SandboxLimit):
        parse_program(src)


def test_eval_step_guard() -> None:
    # a wide expression with more nodes than MAX_EVAL_STEPS
    n = MAX_EVAL_STEPS + 50
    src = " + ".join(["1"] * n)
    node = parse_program(src)
    with pytest.raises(SandboxLimit):
        eval_program(node, {})


def test_integer_bitlength_guard() -> None:
    # 2 ** 70000 far exceeds MAX_INT_BITS
    src = " * ".join(["2"] * (MAX_INT_BITS + 1))
    node = parse_program(src)
    with pytest.raises(SandboxLimit):
        eval_program(node, {})


def test_token_count_guard(challenge: tuple[dict, dict]) -> None:
    full, _ = challenge
    # token_count parses; a program with > MAX_TOKENS tokens is a sandbox hit
    n = MAX_TOKENS + 5
    src = " + ".join(["1"] * n)
    fc = FAMILY.failure_code(full, {"program": src})
    # over the hard cap -> SANDBOX_ERROR (also over budget -> INVALID_SCHEMA;
    # the budget check runs first, so either is acceptable, both non-None)
    assert fc in (ErrorCode.SANDBOX_ERROR, ErrorCode.INVALID_SCHEMA)


# ------------------------------------------------------------------ semantics

@pytest.mark.parametrize(
    "src,inputs,expected",
    [
        ("min(x, y)", [{"x": 3, "y": 5}, {"x": 5, "y": 3}, {"x": -1, "y": 1}], [3, 3, -1]),
        ("max(x, -y)", [{"x": 3, "y": 5}, {"x": 5, "y": 3}], [3, 5]),
        ("abs(x - 7)", [{"x": 7}, {"x": 12}, {"x": 2}], [0, 5, 5]),
        ("-x * 2", [{"x": 3}, {"x": -4}], [-6, 8]),
        ("x % 3", [{"x": 7}, {"x": 9}], [1, 0]),
        ("x // 2", [{"x": 7}, {"x": -7}], [3, -4]),
    ],
)
def test_dsl_semantics(src: str, inputs: list[dict], expected: list[int]) -> None:
    node = parse_program(src)
    for inp, exp in zip(inputs, expected, strict=True):
        assert eval_program(node, dict(inp)) == exp


def test_determinism_across_repeated_verification(challenge: tuple[dict, dict]) -> None:
    full, sol = challenge
    cand = {"program": sol["target_program"]}
    results = {FAMILY.verify(full, cand) for _ in range(50)}
    assert results == {True}
    bad = {"program": "x + 1 - 1 - 1"}
    results = {FAMILY.verify(full, bad) for _ in range(50)}
    assert results == {False}


def test_parse_error_on_garbage() -> None:
    for src in ["", "   ", "@", "1 + @", "min(,)", "abs()", "()"]:
        with pytest.raises((ParseError, SandboxLimit)):
            parse_program(src)
