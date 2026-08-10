"""Random-order baseline for OPT-v0.1 (floor baseline)."""

from __future__ import annotations

import random
from typing import Any

from vica.protocol.models import SolveOutput
from vica.protocol.serialization import stable_hash


class RandomOrderSystem:
    """Random permutation; the absolute floor baseline."""

    system_id = "opt-random"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def config(self) -> dict[str, Any]:
        return {"seed": self.seed}

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        payload = challenge.get("payload", {})
        n = payload.get("n")
        if not isinstance(n, int) or n <= 0:
            raise ValueError("RandomOrderSystem expects an opt-v0.1 payload with n")
        order = list(range(n))
        rng = random.Random(self.seed + int(stable_hash(challenge), 16))
        rng.shuffle(order)
        return SolveOutput(
            candidate={"order": order},
            metadata={"strategy": "random-permutation"},
        )


__all__ = ["RandomOrderSystem"]