"""Tests for the OPT-v0.1 generator (docs/reports/opt-v0.1-design.md)."""

from __future__ import annotations

import pytest

from vica.challenges.opt_v01 import (
    DIFFICULTY_PRESETS,
    FAMILY,
    MAX_DIFFICULTY,
    TYPE_NAME,
    generate,
)
from vica.challenges.registry import build_challenge


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_generate_is_deterministic(difficulty: int) -> None:
    assert generate("seed-a", difficulty) == generate("seed-a", difficulty)
    assert generate("seed-b", difficulty) == generate("seed-b", difficulty)


def test_different_difficulties_produce_different_payloads() -> None:
    assert generate("seed", 1) != generate("seed", 3)


def test_different_seeds_produce_different_payloads() -> None:
    assert generate("seed-a", 2) != generate("seed-b", 2)


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_payload_shape(difficulty: int) -> None:
    payload = generate("shape", difficulty)
    n = DIFFICULTY_PRESETS[difficulty].n
    assert set(payload.keys()) == {"n", "processing", "deadlines"}
    assert payload["n"] == n
    assert len(payload["processing"]) == n
    assert len(payload["deadlines"]) == n
    assert all(p > 0 for p in payload["processing"])
    assert all(d >= 0 for d in payload["deadlines"])


def test_invalid_difficulty_raises() -> None:
    with pytest.raises(ValueError):
        generate("seed", 0)
    with pytest.raises(ValueError):
        generate("seed", MAX_DIFFICULTY + 1)


def test_difficulty_scales_size() -> None:
    assert DIFFICULTY_PRESETS[1].n < DIFFICULTY_PRESETS[5].n


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