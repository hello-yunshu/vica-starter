"""Tests for the SYNTH-v0.1 generator (docs/reports/synth-v0.1-design.md)."""

from __future__ import annotations

import pytest

from vica.challenges.registry import build_challenge
from vica.challenges.synth_v01 import (
    DIFFICULTY_PRESETS,
    FAMILY,
    MAX_DIFFICULTY,
    TYPE_NAME,
    generate,
    generate_with_solution,
    hidden_tests_for,
)


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_generate_is_deterministic(difficulty: int) -> None:
    assert generate("seed-a", difficulty) == generate("seed-a", difficulty)
    assert generate("seed-b", difficulty) == generate("seed-b", difficulty)


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_hidden_solution_verifies(difficulty: int) -> None:
    """The generated target program must pass its own public + hidden tests."""
    payload, sol = generate_with_solution("verify-seed", difficulty)
    challenge = {
        "type": TYPE_NAME,
        "seed": "verify-seed",
        "difficulty": difficulty,
        "payload": payload,
    }
    assert FAMILY.verify(challenge, {"program": sol["target_program"]}) is True
    assert FAMILY.score(challenge, {"program": sol["target_program"]}) == 1.0


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_hidden_tests_regenerate_identically(difficulty: int) -> None:
    """Hidden tests are a pure function of (seed, difficulty)."""
    a = hidden_tests_for("regen-seed", difficulty)
    b = hidden_tests_for("regen-seed", difficulty)
    assert a == b
    assert len(a) == DIFFICULTY_PRESETS[difficulty].hidden_tests


def test_different_difficulties_produce_different_payloads() -> None:
    assert generate("seed", 1) != generate("seed", 3)


def test_different_seeds_produce_different_payloads() -> None:
    assert generate("seed-a", 2) != generate("seed-b", 2)


def test_payload_shape() -> None:
    payload = generate("shape", 2)
    assert set(payload.keys()) == {"function", "public_tests", "input_width", "budget"}
    assert payload["function"]["name"] == "f"
    assert isinstance(payload["function"]["params"], list)
    assert len(payload["public_tests"]) == DIFFICULTY_PRESETS[2].public_tests
    for t in payload["public_tests"]:
        assert set(t.keys()) == {"input", "expected"}
        assert isinstance(t["expected"], int)


def test_payload_contains_no_target_or_hidden_tests() -> None:
    """Public payload must never leak the target program or hidden tests."""
    import json

    payload, sol = generate_with_solution("leak", 3)
    blob = json.dumps(payload, sort_keys=True)
    assert sol["target_program"] not in blob
    for t in sol["hidden_tests"]:
        assert json.dumps(t, sort_keys=True) not in blob


def test_targets_are_non_trivial() -> None:
    """Generated targets must contain at least one operation (no bare var/num)."""
    for difficulty in range(1, MAX_DIFFICULTY + 1):
        for seed in ("t1", "t2", "t3", "t4", "t5"):
            _, sol = generate_with_solution(seed, difficulty)
            src = sol["target_program"]
            # A bare var/num has no operator token. Every real target has at
            # least one of: + - * % // min max abs.
            assert any(op in src for op in ("+", "-", "*", "%", "//", "min", "max", "abs")), (
                difficulty,
                seed,
                src,
            )


def test_invalid_difficulty_raises() -> None:
    with pytest.raises(ValueError):
        generate("seed", 0)
    with pytest.raises(ValueError):
        generate("seed", MAX_DIFFICULTY + 1)


def test_build_challenge_id_stable() -> None:
    a = build_challenge(TYPE_NAME, "seed-1", 2)
    b = build_challenge(TYPE_NAME, "seed-1", 2)
    c = build_challenge(TYPE_NAME, "seed-1", 3)
    d = build_challenge(TYPE_NAME, "seed-2", 2)
    assert a.id == b.id
    assert a.id != c.id
    assert a.id != d.id
    assert a.type == TYPE_NAME
    assert a.generator_version == FAMILY.generator_version


def test_difficulty_scales_operator_pool() -> None:
    """Higher difficulty unlocks more operators / depth."""
    d1 = DIFFICULTY_PRESETS[1]
    d5 = DIFFICULTY_PRESETS[5]
    assert set(d1.ops) < set(d5.ops)
    assert d1.max_depth < d5.max_depth
