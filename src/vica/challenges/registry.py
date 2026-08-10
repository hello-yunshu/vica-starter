"""Challenge registry and challenge-id derivation."""

from __future__ import annotations

from typing import Any

from vica.challenges.csp_v01 import FAMILY as _CSP_FAMILY
from vica.challenges.opt_v01 import FAMILY as _OPT_FAMILY
from vica.challenges.synth_v01 import FAMILY as _SYNTH_FAMILY
from vica.protocol.models import Challenge
from vica.protocol.serialization import canonical_json_bytes, stable_hash
from vica.verifier.interfaces import ChallengeFamily

_REGISTRY: dict[str, ChallengeFamily] = {
    _CSP_FAMILY.type_name: _CSP_FAMILY,
    _SYNTH_FAMILY.type_name: _SYNTH_FAMILY,
    _OPT_FAMILY.type_name: _OPT_FAMILY,
}


def get_family(type_name: str) -> ChallengeFamily:
    """Return the registered ChallengeFamily for *type_name*."""
    try:
        return _REGISTRY[type_name]
    except KeyError:
        raise ValueError(
            f"unknown challenge type {type_name!r}; registered: {sorted(_REGISTRY)}"
        ) from None


def register(family: ChallengeFamily) -> None:
    """Register a ChallengeFamily (mainly for tests / future families)."""
    _REGISTRY[family.type_name] = family


def available_types() -> list[str]:
    return sorted(_REGISTRY)


def build_challenge(
    type_name: str, seed: str, difficulty: int, *, generator_version: str | None = None
) -> Challenge:
    """Generate a Challenge object with a canonical, deterministic id."""
    family = get_family(type_name)
    payload = family.generate(seed, difficulty)
    if generator_version is not None and generator_version != family.generator_version:
        raise ValueError(
            f"generator_version mismatch: requested {generator_version!r}, "
            f"family provides {family.generator_version!r}"
        )

    challenge_without_id: dict[str, Any] = {
        "type": family.type_name,
        "generator_version": family.generator_version,
        "seed": seed,
        "difficulty": difficulty,
        "payload": payload,
    }
    return Challenge(
        id=stable_hash(challenge_without_id),
        type=family.type_name,
        generator_version=family.generator_version,
        seed=seed,
        difficulty=difficulty,
        payload=payload,
    )


def verify_candidate(challenge: dict[str, Any], candidate: Any) -> tuple[bool, float]:
    """Run the family's deterministic verifier on a candidate dict.

    *challenge* is a plain dict carrying ``type``/``payload`` keys (the
    dict-form of a Challenge). Intended for solver self-checks, so it runs on
    public material only: it never carries the verifier secret, meaning SYNTH
    hidden tests are not checked here. The authoritative arena verifier
    (``verify_submission``) is the source of truth. Returns (valid, score).
    Never raises on malformed input.
    """
    try:
        family = get_family(str(challenge["type"]))
        if hasattr(family, "evaluate"):
            result = family.evaluate(challenge, candidate)
            return result.valid, result.score
        valid = family.verify(challenge, candidate)
        score = family.score(challenge, candidate) if valid else 0.0
        return valid, score
    except Exception:
        return False, 0.0


__all__ = [
    "available_types",
    "build_challenge",
    "canonical_json_bytes",
    "get_family",
    "register",
    "verify_candidate",
]