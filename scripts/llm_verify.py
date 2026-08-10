"""Verify inferred LLM programs for the SYNTH-v0.1 probe set.

Loads a JSON mapping instance_id -> inferred DSL expression (produced by the
human/LLM solver from the public tests only), checks each against the hidden
tests, and runs the brute/random baselines on the identical instances to build
the Phase-3 comparison.

Answer file format:
    {"llm:42:3:0": "x % y", ...}

Usage:
    PYTHONPATH=src .venv/bin/python scripts/llm_verify.py path/to/answers.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from vica.challenges.synth_v01.family import (
    FAMILY,
    eval_program,
    generate_with_solution,
    parse_program,
    public_tests_ok,
)
from vica.systems.synth.brute_force import BruteForceSynthSystem
from vica.systems.synth.random_program import RandomProgramSystem

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

SEED = 42
D3_D5_INSTANCES = 10


def instance_ids() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for d in (3, 4, 5):
        out += [(d, i) for i in range(D3_D5_INSTANCES)]
    return out


def _hidden_ok(challenge_id: str, difficulty: int, expr: str) -> bool:
    _, sol = generate_with_solution(challenge_id, difficulty)
    try:
        node = parse_program(expr)
    except Exception:
        return False
    for t in sol["hidden_tests"]:
        try:
            if eval_program(node, dict(t["input"])) != t["expected"]:
                return False
        except Exception:
            return False
    return True


def instance_ids_from(answers: dict) -> list[tuple[int, int]]:
    ids: set[tuple[int, int]] = set()
    for key in answers:
        parts = key.split(":")
        if len(parts) == 4 and parts[0] == "llm":
            ids.add((int(parts[2]), int(parts[3])))
    return sorted(ids)


def main() -> None:
    answers_path = Path(sys.argv[1])
    answers = json.loads(answers_path.read_text())

    brute = BruteForceSynthSystem()
    rnd = RandomProgramSystem()

    rows: list[dict] = []
    for difficulty, i in instance_ids_from(answers):
        cid = f"llm:{SEED}:{difficulty}:{i}"
        payload, sol = generate_with_solution(cid, difficulty)
        challenge = {"payload": payload, "seed": cid, "difficulty": difficulty}

        expr = answers.get(cid)
        llm_hidden = False
        llm_public = False
        if expr is not None and expr.strip():
            llm_public = public_tests_ok(payload, expr)
            llm_hidden = _hidden_ok(cid, difficulty, expr)

        b_out = brute.solve({"payload": payload})
        b_ok = bool(b_out.candidate and FAMILY.verify(challenge, b_out.candidate))

        r_out = rnd.solve({"payload": payload})
        r_ok = bool(r_out.candidate and FAMILY.verify(challenge, r_out.candidate))

        rows.append(
            {
                "id": cid,
                "d": difficulty,
                "expr": expr,
                "llm_pub": llm_public,
                "llm_hidden": llm_hidden,
                "brute_hidden": b_ok,
                "random_hidden": r_ok,
            }
        )

    total = len(rows)
    print(f"instances={total}")
    print(
        f"{'id':<14} {'d':<3} {'llm_pub':<8} {'llm_hid':<8} "
        f"{'brute_hid':<9} {'random_hid':<10} expr"
    )
    for r in rows:
        print(
            f"{r['id']:<14} {r['d']:<3} {str(r['llm_pub']):<8} {str(r['llm_hidden']):<8} "
            f"{str(r['brute_hidden']):<9} {str(r['random_hidden']):<10} "
            f"{(r['expr'] or 'MISSING')[:40]}"
        )

    def rate(key: str) -> float:
        return sum(1 for r in rows if r[key]) / total

    print("\n--- aggregate (hidden verification) ---")
    print(f"llm-one-shot hidden success: {rate('llm_hidden')*100:.1f}%")
    print(f"brute hidden success:        {rate('brute_hidden')*100:.1f}%")
    print(f"random hidden success:       {rate('random_hidden')*100:.1f}%")
    by_d = {}
    for d in (3, 4, 5):
        sub = [r for r in rows if r["d"] == d]
        by_d[d] = {
            "llm": sum(1 for r in sub if r["llm_hidden"]) / len(sub),
            "brute": sum(1 for r in sub if r["brute_hidden"]) / len(sub),
            "random": sum(1 for r in sub if r["random_hidden"]) / len(sub),
            "n": len(sub),
        }
    print("\n--- by difficulty ---")
    for d in (3, 4, 5):
        m = by_d[d]
        print(
            f"d{d}: llm={m['llm']*100:.0f}% brute={m['brute']*100:.0f}% "
            f"random={m['random']*100:.0f}% (n={m['n']})"
        )


if __name__ == "__main__":
    main()