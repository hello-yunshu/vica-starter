"""Verify inferred LLM programs for the SYNTH-v0.1 probe set.

Loads a JSON mapping instance_id -> inferred DSL expression (produced by the
human/LLM solver from the public tests only), checks each against the hidden
tests, and runs the brute/random baselines on the identical instances to build
the Phase-3 comparison.

ALL verification goes through the authoritative arena verifier
(``verify_submission`` with the verifier secret): llm, brute, and random
solutions are all judged by the same hidden-test path that the benchmark uses.
Nothing here is a public-only check.

Answer file format:
    {"llm:42:3:0": "x % y", ...}

Usage:
    PYTHONPATH=src .venv/bin/python scripts/llm_verify.py path/to/answers.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _dev_config import VERIFIER_SECRET

from vica.challenges.registry import build_challenge
from vica.challenges.synth_v01.family import public_tests_ok
from vica.protocol.models import CandidateSubmission
from vica.systems.synth.brute_force import BruteForceSynthSystem
from vica.systems.synth.random_program import RandomProgramSystem
from vica.verifier.verifier import verify_submission

SEED = 42
D3_D5_INSTANCES = 10


def instance_ids_from(answers: dict) -> list[tuple[int, int]]:
    ids: set[tuple[int, int]] = set()
    for key in answers:
        parts = key.split(":")
        if len(parts) == 4 and parts[0] == "llm":
            ids.add((int(parts[2]), int(parts[3])))
    return sorted(ids)


def _authoritative_ok(challenge_id: str, difficulty: int, expr: str) -> bool:
    """True if *expr* passes the authoritative verifier (public + hidden)."""
    challenge = build_challenge(
        "synth-v0.1", challenge_id, difficulty, verifier_secret=VERIFIER_SECRET
    )
    submission = CandidateSubmission(
        challenge_id=challenge.id,
        system_id="llm-verify",
        candidate={"program": expr},
        metadata={},
    )
    return verify_submission(challenge, submission, verifier_secret=VERIFIER_SECRET).valid


def main() -> None:
    answers_path = Path(sys.argv[1])
    answers = json.loads(answers_path.read_text())

    brute = BruteForceSynthSystem()
    rnd = RandomProgramSystem()

    rows: list[dict] = []
    for difficulty, i in instance_ids_from(answers):
        cid = f"llm:{SEED}:{difficulty}:{i}"
        challenge = build_challenge(
            "synth-v0.1", cid, difficulty, verifier_secret=VERIFIER_SECRET
        )
        challenge_dict = challenge.model_dump()

        expr = answers.get(cid)
        llm_public = False
        llm_hidden = False
        if expr is not None and expr.strip():
            # Solver-visible self-check: public tests only (what the solver can
            # see). The headline column (llm_hidden) is the authoritative
            # verifier, which also runs the hidden tests.
            llm_public = public_tests_ok(challenge_dict["payload"], expr)
            llm_hidden = _authoritative_ok(cid, difficulty, expr)

        b_out = brute.solve(challenge_dict)
        b_ok = False
        if b_out.candidate is not None:
            b_sub = CandidateSubmission(
                challenge_id=challenge.id,
                system_id="brute",
                candidate=b_out.candidate,
                metadata={},
            )
            b_ok = verify_submission(
                challenge, b_sub, verifier_secret=VERIFIER_SECRET
            ).valid

        r_out = rnd.solve(challenge_dict)
        r_ok = False
        if r_out.candidate is not None:
            r_sub = CandidateSubmission(
                challenge_id=challenge.id,
                system_id="random",
                candidate=r_out.candidate,
                metadata={},
            )
            r_ok = verify_submission(
                challenge, r_sub, verifier_secret=VERIFIER_SECRET
            ).valid

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

    print("\n--- aggregate (authoritative hidden verification) ---")
    print(f"llm-one-shot hidden success: {rate('llm_hidden')*100:.1f}%")
    print(f"brute hidden success:        {rate('brute_hidden')*100:.1f}%")
    print(f"random hidden success:       {rate('random_hidden')*100:.1f}%")
    by_d = {}
    for d in (3, 4, 5):
        sub = [r for r in rows if r["d"] == d]
        if not sub:
            by_d[d] = {"llm": None, "brute": None, "random": None, "n": 0}
            continue
        by_d[d] = {
            "llm": sum(1 for r in sub if r["llm_hidden"]) / len(sub),
            "brute": sum(1 for r in sub if r["brute_hidden"]) / len(sub),
            "random": sum(1 for r in sub if r["random_hidden"]) / len(sub),
            "n": len(sub),
        }
    print("\n--- by difficulty ---")
    for d in (3, 4, 5):
        m = by_d[d]
        if m["n"] == 0:
            print(f"d{d}: no instances in answer file")
            continue
        print(
            f"d{d}: llm={m['llm']*100:.0f}% brute={m['brute']*100:.0f}% "
            f"random={m['random']*100:.0f}% (n={m['n']})"
        )


if __name__ == "__main__":
    main()