"""Brute-force enumerative baseline for SYNTH-v0.1.

The traditional-solver baseline required by AGENTS.md invariant #5. Performs
size-bounded enumerative search over the DSL: generate every expression tree
of increasing node count (1, 2, 3, ...) using the public variables and a
small constant set derived from the public tests, and return the first tree
that reproduces every public (input -> output) example.

This directly tests design-doc Risk 1: whether SYNTH-v0.1 can be brute-forced.
For trivial/low-difficulty targets it should succeed; for deeper targets it
is expected to time out — that is a valid research result, not a bug.

The arena verifier remains the authority; this system only uses the public
tests for its own self-check.
"""

from __future__ import annotations

import time
from typing import Any

from vica.challenges.synth_v01.family import eval_program, parse_program, program_to_source
from vica.protocol.models import SolveOutput

# Search budget. Node-count enumeration grows combinatorially, so the caps
# matter more than the theoretical search space.
_DEFAULT_MAX_NODES = 13
_DEFAULT_MAX_CANDIDATES = 200_000
_DEFAULT_MAX_SECONDS = 10.0
_CONST_RANGE = 20  # constants drawn from [-_CONST_RANGE, _CONST_RANGE]

_BINARY_OPS = ("+", "-", "*", "%", "//", "min", "max")
_UNARY_OPS = ("neg", "abs")


def _public_tests_pass(ast: tuple[Any, ...], public_tests: list[dict[str, Any]]) -> bool:
    for t in public_tests:
        try:
            if eval_program(ast, dict(t["input"])) != t["expected"]:
                return False
        except Exception:
            return False
    return True


def _constant_pool(public_tests: list[dict[str, Any]]) -> list[int]:
    seen: set[int] = set()
    pool: list[int] = []
    for t in public_tests:
        for v in [t.get("expected")]:
            if isinstance(v, int) and -_CONST_RANGE <= v <= _CONST_RANGE and v not in seen:
                seen.add(v)
                pool.append(v)
        for v in t.get("input", {}).values():
            if isinstance(v, int) and -_CONST_RANGE <= v <= _CONST_RANGE and v not in seen:
                seen.add(v)
                pool.append(v)
    # Always include 0, 1, -1 as fallback building blocks.
    for c in (0, 1, -1):
        if c not in seen:
            seen.add(c)
            pool.append(c)
    return pool


class BruteForceSynthSystem:
    """Enumerative program search; the traditional-solver baseline."""

    system_id = "synth-brute"

    def __init__(
        self,
        max_nodes: int = _DEFAULT_MAX_NODES,
        max_candidates: int = _DEFAULT_MAX_CANDIDATES,
        max_seconds: float = _DEFAULT_MAX_SECONDS,
    ) -> None:
        self.max_nodes = max_nodes
        self.max_candidates = max_candidates
        self.max_seconds = max_seconds

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        if isinstance(challenge, dict):
            payload: dict[str, Any] = challenge.get("payload", {})
        else:
            payload = {}
        public_tests = payload.get("public_tests")
        if not isinstance(public_tests, list) or not public_tests:
            raise ValueError("BruteForceSynthSystem expects a synth-v0.1 payload with public_tests")

        params = list(payload.get("function", {}).get("params") or ("x",))
        consts = _constant_pool(public_tests)

        # Leaves: variables and constants.
        leaves: list[tuple[Any, ...]] = [("var", p) for p in params] + [("num", c) for c in consts]

        start = time.perf_counter()
        checked = 0
        # trees_by_size[n] = list of ASTs with exactly n nodes (deduped by source).
        trees_by_size: dict[int, list[tuple[Any, ...]]] = {1: list(leaves)}

        def budget_exceeded() -> bool:
            return checked >= self.max_candidates or time.perf_counter() - start > self.max_seconds

        # Size 1 first.
        for ast in trees_by_size[1]:
            checked += 1
            if _public_tests_pass(ast, public_tests):
                return self._done(ast, checked, start)
            if budget_exceeded():
                return self._done(None, checked, start)

        for n in range(2, self.max_nodes + 1):
            trees_n: list[tuple[Any, ...]] = []
            seen_src: set[str] = set()

            # Unary: unary(t) where size(t) = n - 1.
            if n - 1 >= 1:
                for t in trees_by_size.get(n - 1, ()):
                    for u in _UNARY_OPS:
                        ast = (u, t)
                        src = program_to_source(ast)
                        if src in seen_src:
                            continue
                        seen_src.add(src)
                        trees_n.append(ast)
                        checked += 1
                        if _public_tests_pass(ast, public_tests):
                            return self._done(ast, checked, start)
                        if budget_exceeded():
                            trees_by_size[n] = trees_n
                            return self._done(None, checked, start)

            # Binary: binary(left, right) where size(left) + size(right) = n - 1.
            for size_l in range(1, n - 1):
                size_r = n - 1 - size_l
                if size_r < 1:
                    continue
                lefts = trees_by_size.get(size_l, ())
                rights = trees_by_size.get(size_r, ())
                if not lefts or not rights:
                    continue
                for left_ast in lefts:
                    for right_ast in rights:
                        for op in _BINARY_OPS:
                            ast = (op, left_ast, right_ast)
                            src = program_to_source(ast)
                            if src in seen_src:
                                continue
                            seen_src.add(src)
                            trees_n.append(ast)
                            checked += 1
                            if _public_tests_pass(ast, public_tests):
                                return self._done(ast, checked, start)
                            if budget_exceeded():
                                trees_by_size[n] = trees_n
                                return self._done(None, checked, start)

            trees_by_size[n] = trees_n
            if time.perf_counter() - start > self.max_seconds:
                break

        return self._done(None, checked, start)

    @staticmethod
    def _done(ast: tuple[Any, ...] | None, checked: int, start: float) -> SolveOutput:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metadata = {
            "strategy": "brute-force-enum",
            "candidates_checked": checked,
            "solve_wall_time_ms": elapsed_ms,
        }
        if ast is None:
            return SolveOutput(candidate=None, metadata=metadata)
        # Round-trip through the parser to guarantee a valid candidate string.
        src = program_to_source(ast)
        try:
            parse_program(src)  # sanity; should always parse
        except Exception:
            return SolveOutput(candidate=None, metadata=metadata)
        return SolveOutput(candidate={"program": src}, metadata=metadata)


__all__ = ["BruteForceSynthSystem"]
