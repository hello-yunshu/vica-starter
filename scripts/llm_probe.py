"""LLM comparison probe for SYNTH-v0.1.

Generates a fixed, deterministic set of challenges and prints each one's
10 public (input -> output) examples WITHOUT revealing the target program.
The human/LLM solver reads these examples, infers a DSL expression, and the
inferred programs are recorded in an answers JSON that

    scripts/llm_verify.py

then checks against the hidden tests and compares with the brute/random
baselines on the identical instances.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/llm_probe.py [--d1d2] > /tmp/llm_probe.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _dev_config import VERIFIER_SECRET

from vica.challenges.synth_v01.family import generate_with_solution

SEED = 42
D3_D5_INSTANCES = 10
D1D2_INSTANCES = 5


def main() -> None:
    include_low = "--d1d2" in sys.argv
    instances: list[tuple[int, int]] = []
    for d in (3, 4, 5):
        instances += [(d, i) for i in range(D3_D5_INSTANCES)]
    if include_low:
        for d in (1, 2):
            instances += [(d, i) for i in range(D1D2_INSTANCES)]

    print(json.dumps({"seed": SEED, "instances": len(instances)}))
    for difficulty, i in instances:
        challenge_id = f"llm:{SEED}:{difficulty}:{i}"
        payload, sol = generate_with_solution(challenge_id, difficulty, VERIFIER_SECRET)
        fn = payload["function"]
        print("\n" + "=" * 60)
        print(f"INSTANCE d{difficulty} #{i}  id={challenge_id}")
        print(f"function f({', '.join(fn['params'])})")
        print("public tests:")
        for t in payload["public_tests"]:
            inp = ", ".join(f"{k}={v}" for k, v in t["input"].items())
            print(f"  f({inp}) -> {t['expected']}")
        # target NOT printed; kept only for the verifying script


if __name__ == "__main__":
    main()