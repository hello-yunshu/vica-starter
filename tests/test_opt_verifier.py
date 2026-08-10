"""Tests for the OPT-v0.1 deterministic verifier."""

from __future__ import annotations

import pytest

from vica.challenges.opt_v01 import FAMILY, TYPE_NAME, generate, score_order
from vica.protocol.models import ErrorCode


def _challenge(seed: str = "v", difficulty: int = 2) -> dict:
    return {
        "type": TYPE_NAME,
        "seed": seed,
        "difficulty": difficulty,
        "payload": generate(seed, difficulty),
    }


def test_score_is_hand_computable() -> None:
    """Manual instance: p=[3,2,1], d=[10,5,3]."""
    processing = [3, 2, 1]
    deadlines = [10, 5, 3]
    order = [0, 1, 2]
    # C0=3(<=10 ok), C1=5(<=5 ok), C2=6(<=3? tardy 3)
    assert score_order(processing, deadlines, order) == -3
    order2 = [2, 1, 0]
    # C2=1(<=3), C1=3(<=5), C0=6(<=10) => zero tardiness
    assert score_order(processing, deadlines, order2) == 0


def test_valid_permutation_is_accepted() -> None:
    ch = _challenge()
    n = ch["payload"]["n"]
    for order in (list(range(n)), list(range(n - 1, -1, -1))):
        assert FAMILY.verify(ch, {"order": order}) is True
        assert FAMILY.failure_code(ch, {"order": order}) is None


@pytest.mark.parametrize(
    "candidate",
    [
        {},
        {"order": None},
        {"order": "abc"},
        {"order": [0]},  # wrong length
        {"order": [0, 1, 0]},  # duplicate
        {"order": [0, 1, 99]},  # out of range
        {"order": [0, 1, "x"]},  # non-int
        {"order": [0, 1, True]},  # bool is not a valid index
    ],
)
def test_malformed_candidates_are_rejected(candidate: dict) -> None:
    ch = _challenge()
    assert FAMILY.verify(ch, candidate) is False
    assert FAMILY.failure_code(ch, candidate) == ErrorCode.INVALID_SCHEMA


def test_non_dict_candidate_never_crashes() -> None:
    ch = _challenge()
    for bad in (None, 3, "x", [0, 1], {"no_order": []}):
        # verify/failure_code must not raise
        assert FAMILY.verify(ch, bad) is False
        assert FAMILY.failure_code(ch, bad) is not None


def test_score_matches_verifier_for_valid() -> None:
    ch = _challenge("score", 1)
    n = ch["payload"]["n"]
    order = list(range(n))
    assert score_order(ch["payload"]["processing"], ch["payload"]["deadlines"], order) == (
        FAMILY.score(ch, {"order": order})
    )


def test_verifier_is_deterministic() -> None:
    ch = _challenge("det", 3)
    n = ch["payload"]["n"]
    order = list(range(n))
    assert FAMILY.failure_code(ch, {"order": order}) == FAMILY.failure_code(
        dict(ch), {"order": order}
    )
    assert FAMILY.score(ch, {"order": order}) == FAMILY.score(dict(ch), {"order": order})