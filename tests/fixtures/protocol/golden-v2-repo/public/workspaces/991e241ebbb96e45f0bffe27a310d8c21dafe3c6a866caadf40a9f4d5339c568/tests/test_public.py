"""Public tests for the storage task (REPO-v0.1)."""
from __future__ import annotations

import solution


def test_public_cases() -> None:
    cases = [
        ([('begin',), ('set', 'a', 'v'), ('rollback',), ('get', 'c')], [None]),
        ([('begin',), ('set', 'a', 'y'), ('rollback',), ('get', 'b')], [None]),
        ([('begin',), ('set', 'k', 'x'), ('set', 'b', 'v'), ('rollback',), ('get', 'c')], [None]),
        ([('begin',), ('set', 'k', 'v'), ('rollback',), ('get', 'k')], [None]),
    ]
    for i, (args, expected) in enumerate(cases):
        got = solution.solve(*args)
        assert got == expected, f'case {i}: got {got!r}, expected {expected!r}'
