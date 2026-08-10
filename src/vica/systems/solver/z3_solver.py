"""Traditional solver baseline using Z3 (SMT).

Converts a CSP-v0.1 payload to Z3 Int constraints, solves with a timeout,
and returns the model — if any — as the candidate.

Per project rules the returned candidate is still passed through the VICA
deterministic verifier by the runner; the solver's own verdict never
bypasses it.
"""

from __future__ import annotations

import time
from typing import Any

from vica.protocol.models import SolveOutput

try:  # pragma: no cover - import guard
    import z3
except ImportError:  # pragma: no cover
    z3 = None  # type: ignore[assignment]


class Z3SolverSystem:
    """Z3-backed satisfiability baseline for CSP-v0.1 payloads."""

    system_id = "z3"

    def __init__(self, timeout_ms: int = 5000) -> None:
        self.timeout_ms = timeout_ms

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        if z3 is None:
            raise RuntimeError("z3-solver is not installed (pip install 'vica[solver]')")
        payload: dict[str, Any] = challenge.get("payload", {})
        if not isinstance(payload, dict) or "variables" not in payload:
            raise ValueError("Z3SolverSystem expects a csp-style challenge payload")

        variables: list[str] = payload["variables"]
        min_v = int(payload["min_value"])
        max_v = int(payload["max_value"])
        bits = max(1, max_v.bit_length())

        start = time.perf_counter()
        x = {v: z3.Int(v) for v in variables}
        solver = z3.Solver()
        solver.set(timeout=self.timeout_ms)
        for v in variables:
            solver.add(x[v] >= min_v, x[v] <= max_v)

        for c in payload.get("constraints", []):
            solver.add(_translate(c, x, bits))

        sat_status = solver.check()
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        candidate: dict[str, int] | None = None
        if sat_status == z3.sat:
            model = solver.model()
            candidate = {v: int(model.eval(x[v]).as_long()) for v in variables}

        metadata = {
            "strategy": f"z3:{sat_status}",
            "attempts": 1,
            "solve_wall_time_ms": elapsed_ms,
        }
        return SolveOutput(candidate=candidate, metadata=metadata)


def _bit01(expr: Any, i: int) -> Any:
    """The value of bit *i* of an Int expression, as an Int expression (0/1)."""
    return z3.If((expr % 2 ** (i + 1)) >= 2**i, 1, 0)


def _xor_int(a: Any, b: Any, target: int, bits: int) -> Any:
    """Encode ``a XOR b == target`` for Int-typed a/b (bounded by 2**bits).

    XOR has no carries, so it holds iff the parity of each bit equals the
    corresponding target bit.
    """
    per_bit = []
    for i in range(bits):
        ai = _bit01(a, i)
        bi = _bit01(b, i)
        ti = z3.IntVal((target >> i) & 1)
        per_bit.append((ai + bi) % 2 == ti)
    return z3.And(per_bit)


def _translate(c: dict[str, Any], x: dict[str, Any], bits: int = 5) -> Any:
    """Translate one payload constraint into a Z3 expression."""
    op = c["op"]
    vs = [x[str(v)] for v in c["vars"]]
    if op == "eq":
        return vs[0] == vs[1]
    if op == "ne":
        return vs[0] != vs[1]
    if op == "lt":
        return vs[0] < vs[1]
    if op == "add":
        return vs[0] + vs[1] == int(c["target"])
    if op == "xor":
        return _xor_int(vs[0], vs[1], int(c["target"]), bits)
    if op == "mod_sum":
        mod = int(c.get("mod", 31))
        return sum(vs) % mod == int(c["target"])
    if op == "linear":
        coeffs = [int(k) for k in c["coeffs"]]
        return sum(k * v for k, v in zip(coeffs, vs, strict=True)) == int(c["target"])
    if op == "all_diff":
        return z3.Distinct(vs)
    raise ValueError(f"unknown constraint operator: {op!r}")


__all__ = ["Z3SolverSystem", "_translate", "_xor_int"]