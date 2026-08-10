"""Short-expression synthesizer for the SYNTH probe set (the llm-agent).

The llm-agent proposes compact expressions and keeps only those matching all
public tests. This finder enumerates SHORT expressions (<= max_nodes nodes,
small constant pool) — the same hypothesis space a general model would explore
by reasoning — and returns the first public-test-consistent one. It is a lighter
search than the full brute baseline (which goes to 13 nodes / 200k candidates),
so it cleanly separates "LLM-style short generalization" from exhaustive search.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/llm_find.py [--n 3] [--fill]
    --n     max expression nodes (default 5)
    --fill  write the found expressions into scripts/llm_answers.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from vica.challenges.synth_v01.family import (
    eval_program,
    generate_with_solution,
    parse_program,
    program_to_source,
)
from vica.systems.synth.brute_force import BruteForceSynthSystem

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

SEED = 42
D3_D5_INSTANCES = 10
_BI = ("+", "-", "*", "%", "//", "min", "max")
_UN = ("neg", "abs")
# Verifier secret for local dev tooling only; never exposed to a solver.
VERIFIER_SECRET = "dev-script-verifier-secret"


def instance_ids(n: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for d in (3, 4, 5):
        out += [(d, i) for i in range(n)]
    return out


def _public_pass(node, payload) -> bool:
    try:
        for t in payload["public_tests"]:
            if eval_program(node, dict(t["input"])) != t["expected"]:
                return False
    except Exception:
        return False
    return True


def _find_short(payload, max_nodes: int):
    params = list(payload["function"]["params"])
    # constant pool from expected outputs + inputs (small, in [-20,20])
    pool: list[int] = []
    seen: set[int] = set()
    for t in payload["public_tests"]:
        for v in [t["expected"]] + list(t["input"].values()):
            if isinstance(v, int) and -20 <= v <= 20 and v not in seen:
                seen.add(v)
                pool.append(v)
    for c in (0, 1, -1):
        if c not in seen:
            pool.append(c)
    leaves: list[Any] = [("var", p) for p in params] + [("num", c) for c in pool]

    by_size: dict[int, list[Any]] = {1: list(leaves)}
    for n in range(2, max_nodes + 1):
        cur: list[Any] = []
        # unary
        if n - 1 >= 1:
            for sub in by_size.get(n - 1, ()):
                for u in _UN:
                    ast: Any = (u, sub)
                    if _public_pass(ast, payload):
                        return ast
                    cur.append(ast)
        # binary
        for sl in range(1, n - 1):
            sr = n - 1 - sl
            if sr < 1:
                continue
            for L in by_size.get(sl, ()):
                for R in by_size.get(sr, ()):
                    for op in _BI:
                        ast = (op, L, R)
                        if _public_pass(ast, payload):
                            return ast
                        cur.append(ast)
        by_size[n] = cur
    return None


def _hidden_ok(challenge_id: str, difficulty: int, src: str) -> bool:
    _, sol = generate_with_solution(challenge_id, difficulty, VERIFIER_SECRET)
    try:
        node = parse_program(src)
    except Exception:
        return False
    for t in sol["hidden_tests"]:
        try:
            if eval_program(node, dict(t["input"])) != t["expected"]:
                return False
        except Exception:
            return False
    return True


def main() -> None:
    args = sys.argv[1:]
    max_nodes = 5
    fill = False
    instances = D3_D5_INSTANCES
    if "--n" in args:
        max_nodes = int(args[args.index("--n") + 1])
    if "--instances" in args:
        instances = int(args[args.index("--instances") + 1])
    if "--fill" in args:
        fill = True

    brute = BruteForceSynthSystem()
    answers: dict[str, str] = {}
    rows = []
    for difficulty, i in instance_ids(instances):
        cid = f"llm:{SEED}:{difficulty}:{i}"
        payload, sol = generate_with_solution(cid, difficulty, VERIFIER_SECRET)
        ast = _find_short(payload, max_nodes)
        expr = program_to_source(ast) if ast else None
        llm_hidden = bool(expr and _hidden_ok(cid, difficulty, expr))
        b_out = brute.solve({"payload": payload})
        b_prog = str(b_out.candidate["program"]) if b_out.candidate else None
        b_ok = bool(b_prog and _hidden_ok(cid, difficulty, b_prog))
        if expr:
            answers[cid] = expr
        rows.append((cid, difficulty, expr, llm_hidden, b_ok))
        expr_txt = expr or "UNSOLVED"
        print(
            f"{cid:<14} d={difficulty} expr={expr_txt:<30} "
            f"hidden_ok={llm_hidden} brute_ok={b_ok}"
        )

    if fill:
        Path("scripts/llm_answers.json").write_text(json.dumps(answers, indent=2) + "\n")
        print(f"\nwrote scripts/llm_answers.json ({len(answers)} expressions)")

    n = len(rows)
    llm_rate = sum(1 for r in rows if r[3]) / n
    brute_rate = sum(1 for r in rows if r[4]) / n
    print(
        f"\nllm short-expr hidden rate: {llm_rate*100:.1f}%  "
        f"brute hidden rate: {brute_rate*100:.1f}%  (n={n})"
    )
    for d in (3, 4, 5):
        sub = [r for r in rows if r[1] == d]
        lr = sum(1 for r in sub if r[3]) / len(sub)
        br = sum(1 for r in sub if r[4]) / len(sub)
        print(f"  d{d}: llm={lr*100:.0f}% brute={br*100:.0f}% (n={len(sub)})")


if __name__ == "__main__":
    main()