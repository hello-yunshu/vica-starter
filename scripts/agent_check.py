"""Interactive agent self-check for the SYNTH-v0.1 probe set.

Mirrors the llm-agent loop: given a candidate DSL expression, report whether it
matches all public tests, and if not, return the first failing (input, got,
expected) as feedback so the solver can refine.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/agent_check.py llm:42:3:0 "x % y"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _dev_config import VERIFIER_SECRET

from vica.challenges.synth_v01.family import eval_program, generate_with_solution, parse_program


def main() -> None:
    cid = sys.argv[1]
    expr = sys.argv[2]
    *_, d_str, _i_str = cid.split(":")
    difficulty = int(d_str)
    payload, _ = generate_with_solution(cid, difficulty, VERIFIER_SECRET)

    try:
        node = parse_program(expr)
    except Exception as exc:
        print(f"PARSE ERROR: {exc}")
        return

    n_pass = 0
    for t in payload["public_tests"]:
        inp = ", ".join(f"{k}={v}" for k, v in t["input"].items())
        try:
            got = eval_program(node, dict(t["input"]))
        except Exception as exc:
            print(f"EVAL ERROR f({inp}): {exc}")
            return
        if got == t["expected"]:
            n_pass += 1
        else:
            print(f"FAIL f({inp}) -> {got}, expected {t['expected']}")
            print(f"public pass: {n_pass}/{len(payload['public_tests'])}")
            return
    print(f"ALL {n_pass} public tests PASS")


if __name__ == "__main__":
    main()