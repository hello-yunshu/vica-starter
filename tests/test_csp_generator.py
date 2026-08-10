"""Tests for the CSP-v0.1 generator."""

from __future__ import annotations

import pytest

from vica.challenges.csp_v01 import (
    DIFFICULTY_PRESETS,
    FAMILY,
    MAX_DIFFICULTY,
    TYPE_NAME,
    generate,
    generate_with_solution,
)
from vica.challenges.registry import build_challenge


@pytest.mark.parametrize("difficulty", [1, 2, 3, 5, 8])
def test_generate_is_deterministic(difficulty: int) -> None:
    assert generate("seed-a", difficulty) == generate("seed-a", difficulty)
    assert generate("seed-b", difficulty) == generate("seed-b", difficulty)


@pytest.mark.parametrize("difficulty", [1, 2, 3, 5, 8])
def test_hidden_solution_satisfies_all_constraints(difficulty: int) -> None:
    payload, solution = generate_with_solution("seed-x", difficulty)
    assert FAMILY.verify(payload, solution) is True
    assert FAMILY.score(payload, solution) == 1.0


def test_difficulty_scales_variable_count() -> None:
    counts: dict[int, int] = {}
    for difficulty in range(1, MAX_DIFFICULTY + 1):
        payload = generate("seed", difficulty)
        expected_vars, expected_constraints = DIFFICULTY_PRESETS[difficulty]
        assert len(payload["variables"]) == expected_vars
        assert len(payload["constraints"]) == expected_constraints
        counts[difficulty] = expected_vars
    # strictly increasing in difficulty
    assert counts == dict(sorted(counts.items()))
    assert list(counts.values()) == sorted(set(counts.values()))


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_constraint_count_always_exactly_matches_preset(difficulty: int) -> None:
    """A seed sweep must never emit a weaker instance: len(constraints) always
    equals the preset target count (SPEC 10, P1 CSP integrity)."""
    _, expected_constraints = DIFFICULTY_PRESETS[difficulty]
    for i in range(120):
        payload = generate(f"integrity-sweep-{i}", difficulty)
        assert len(payload["constraints"]) == expected_constraints


def test_different_difficulties_never_same_payload() -> None:
    p1 = generate("seed", 1)
    p3 = generate("seed", 3)
    assert p1 != p3


def test_payload_contains_no_solution_leak() -> None:
    payload, solution = generate_with_solution("leak-check", 4)
    # The hidden solution must never be recognizable inside the public
    # payload. Individual hidden values may legitimately coincide with
    # constraint targets, but a full assignment must not appear as data.
    import json

    blob = json.dumps(payload, sort_keys=True)
    # a complete assignment {"A0": v0, "A1": v1, ...} would be a leak;
    # spot-check for the serialized sub-dict of a few variables
    subset = dict(list(solution.items())[:3])
    assert json.dumps(subset, sort_keys=True).replace(" ", "") not in blob.replace(" ", "")


def test_invalid_difficulty_raises() -> None:
    with pytest.raises(ValueError):
        generate("seed", MAX_DIFFICULTY + 1)
    with pytest.raises(ValueError):
        generate("seed", 0)


def test_build_challenge_id_stable() -> None:
    a = build_challenge(TYPE_NAME, "seed-1", 2)
    b = build_challenge(TYPE_NAME, "seed-1", 2)
    c = build_challenge(TYPE_NAME, "seed-1", 3)
    assert a.id == b.id
    assert a.id != c.id
    assert a.type == TYPE_NAME
    assert a.generator_version == FAMILY.generator_version


def test_constraint_operators_present() -> None:
    payload = generate("ops-check", 4)
    ops = {c["op"] for c in payload["constraints"]}
    # xor is rare; ensure core ops exist across difficulties
    for difficulty in range(1, MAX_DIFFICULTY + 1):
        ops.update(c["op"] for c in generate("ops-check", difficulty)["constraints"])
    assert {"eq", "ne", "lt", "add", "mod_sum", "linear"} <= ops