"""SYNTH-v0.1 target-complexity + ambiguity probe (Challenge Research Lab).

Measures two research questions from docs/challenge-research/synth/:

1. TARGET COMPLEXITY  — for a (secret, seed, difficulty), how complex is the
   reference target? Reports AST depth, node count, operator count, program
   length, input width, per difficulty.

2. PUBLIC AMBIGUITY   — how many distinct programs within budget fit all 10
   public examples? A large count means the challenge measures inductive bias /
   generalization rather than unique reverse-engineering (allowed, but must be
   acknowledged). A small count (near 1) means the public examples pin the
   target down.

This is research tooling, not a product solver. It requires a verifier secret
to regenerate the target and hidden material (the authority's path). It does
not modify any challenge or benchmark data.

Usage:
    python scripts/analyze_synth_ambiguity.py [--secret <hex>] [--difficulty 1-5]
        [--instances 5] [--seed 42] [--max-ambiguity-candidates 20000]
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vica.challenges.synth_v01.family import (  # noqa: E402
    DIFFICULTY_PRESETS,
    _node_count,
    eval_program,
    generate_with_solution,
    parse_program,
    program_to_source,
)
from vica.systems.synth.brute_force import _BINARY_OPS, _UNARY_OPS, _constant_pool  # noqa: E402


def _ast_depth(node: tuple[Any, ...]) -> int:
    kind = node[0]
    if kind in ("num", "var"):
        return 1
    if kind in ("neg", "abs"):
        return 1 + _ast_depth(node[1])
    return 1 + max(_ast_depth(node[1]), _ast_depth(node[2]))


def _operator_count(node: tuple[Any, ...]) -> int:
    kind = node[0]
    if kind in ("num", "var"):
        return 0
    if kind in ("neg", "abs"):
        return 1 + _operator_count(node[1])
    return 1 + _operator_count(node[1]) + _operator_count(node[2])


def _target_complexity(seed: str, difficulty: int, secret: str) -> dict[str, Any]:
    payload, solution = generate_with_solution(seed, difficulty, secret)
    target_src = solution["target_program"]
    ast = parse_program(target_src)
    op_types = sorted({str(n[0]) for n in _collect_ops(ast)})
    return {
        "difficulty": difficulty,
        "target_src": target_src,
        "ast_depth": _ast_depth(ast),
        "node_count": _node_count(ast),
        "operator_count": _operator_count(ast),
        "operator_types": op_types,
        "input_width": payload.get("input_width"),
        "params": list(payload.get("function", {}).get("params") or ()),
        "public_examples": len(payload.get("public_tests") or ()),
        "hidden_tests": len(solution.get("hidden_tests") or ()),
    }


def _collect_ops(node: tuple[Any, ...]) -> list[Any]:
    kind = node[0]
    out: list[Any] = []
    if kind in ("num", "var"):
        return out
    out.append((kind, node[1] if kind in ("neg", "abs") else node[2]))
    for child in node[1:]:
        if isinstance(child, tuple):
            out.extend(_collect_ops(child))
    return out


def _publicly_consistent(
    target_src: str, seed: str, difficulty: int, secret: str, max_candidates: int
) -> dict[str, Any]:
    """Count distinct programs within budget that fit all public examples.

    Enumerates expressions by node count (same strategy as the brute baseline)
    up to a candidate cap, and counts how many distinct source strings reproduce
    every public example. The target itself is guaranteed to be among them.
    """
    payload, _ = generate_with_solution(seed, difficulty, secret)
    public_tests = payload.get("public_tests") or ()
    params = list(payload.get("function", {}).get("params") or ("x",))
    consts = _constant_pool(public_tests)
    leaves: list[tuple[Any, ...]] = [("var", p) for p in params] + [("num", c) for c in consts]

    def fits(ast: tuple[Any, ...]) -> bool:
        for t in public_tests:
            try:
                if eval_program(ast, dict(t["input"])) != t["expected"]:
                    return False
            except Exception:
                return False
        return True

    trees_by_size: dict[int, list[tuple[Any, ...]]] = {1: list(leaves)}
    consistent: set[str] = set()
    checked = 0

    def note(ast: tuple[Any, ...], src: str) -> None:
        nonlocal checked
        checked += 1
        if checked > max_candidates:
            return
        if fits(ast):
            consistent.add(src)

    def capped() -> bool:
        return checked > max_candidates

    for ast in trees_by_size[1]:
        note(ast, program_to_source(ast))
        if capped():
            return _ambig_result(consistent, checked, target_src, capped=True)

    max_nodes = min(13, _node_count(parse_program(target_src)) + 2)
    for n in range(2, max_nodes + 1):
        trees_n: list[tuple[Any, ...]] = []
        seen_src: set[str] = set()
        if n - 1 >= 1:
            for t in trees_by_size.get(n - 1, ()):
                for u in _UNARY_OPS:
                    ast = (u, t)
                    src = program_to_source(ast)
                    if src in seen_src:
                        continue
                    seen_src.add(src)
                    trees_n.append(ast)
                    note(ast, src)
                    if capped():
                        return _ambig_result(consistent, checked, target_src, capped=True)
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
                        note(ast, src)
                        if capped():
                            return _ambig_result(consistent, checked, target_src, capped=True)
        trees_by_size[n] = trees_n
    return _ambig_result(consistent, checked, target_src, capped=False)


def _ambig_result(
    consistent: set[str], checked: int, target_src: str, capped: bool
) -> dict[str, Any]:
    return {
        "count": None if capped else len(consistent),
        "checked": checked,
        "capped": capped,
        "target_found": target_src in consistent,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--secret", default=None, help="verifier secret (default: random)")
    parser.add_argument("--difficulty", default="1-5", help="difficulty range, e.g. 1-5")
    parser.add_argument("--instances", type=int, default=5, help="instances per difficulty")
    parser.add_argument("--seed", type=int, default=42, help="evaluation seed")
    parser.add_argument("--max-ambiguity-candidates", type=int, default=20_000)
    args = parser.parse_args()

    secret = args.secret or secrets.token_hex(32)
    lo, _, hi = args.difficulty.partition("-")
    if not hi:
        hi = lo
    difficulties = range(int(lo), int(hi) + 1)

    print(f"secret={secret[:8]}... (id: not shown) instances={args.instances} seed={args.seed}")
    print("difficulty | target | depth | nodes | ops | op-types | pub | hid | ambiguity")
    print("-----------|--------|-------|-------|-----|----------|-----|-----|----------")
    for difficulty in difficulties:
        if difficulty not in DIFFICULTY_PRESETS:
            print(f"d{difficulty}: unsupported")
            continue
        for i in range(args.instances):
            seed = f"{args.seed}:{difficulty}:{i}"
            tc = _target_complexity(seed, difficulty, secret)
            amb = _publicly_consistent(
                tc["target_src"], seed, difficulty, secret, args.max_ambiguity_candidates
            )
            amb_txt = (
                f"{amb['count']}"
                if amb["count"] is not None
                else f">={amb['checked']} (capped)"
            )
            print(
                f"d{difficulty}   | {tc['target_src'][:28]:28s} | {tc['ast_depth']:5d} | "
                f"{tc['node_count']:5d} | {tc['operator_count']:3d} | "
                f"{','.join(tc['operator_types'])[:12]:12s} | {tc['public_examples']:3d} | "
                f"{tc['hidden_tests']:3d} | {amb_txt}"
            )


if __name__ == "__main__":
    main()