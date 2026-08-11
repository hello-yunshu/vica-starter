"""Challenge registry and challenge-id derivation."""

from __future__ import annotations

from typing import Any

from vica.challenges.csp_v01 import FAMILY as _CSP_FAMILY
from vica.challenges.opt_v01 import FAMILY as _OPT_FAMILY
from vica.challenges.synth_v01 import FAMILY as _SYNTH_FAMILY
from vica.protocol.models import Challenge
from vica.protocol.serialization import canonical_json_bytes, stable_hash
from vica.repo.family import FAMILY as _REPO_FAMILY
from vica.verifier.interfaces import ChallengeFamily
from vica.verifier.material import verifier_material_commitment

_REGISTRY: dict[str, ChallengeFamily] = {
    _CSP_FAMILY.type_name: _CSP_FAMILY,
    _SYNTH_FAMILY.type_name: _SYNTH_FAMILY,
    _OPT_FAMILY.type_name: _OPT_FAMILY,
    _REPO_FAMILY.type_name: _REPO_FAMILY,
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
    type_name: str,
    seed: str,
    difficulty: int,
    *,
    generator_version: str | None = None,
    verifier_secret: str | None = None,
) -> Challenge:
    """Generate a Challenge object with a canonical, deterministic id.

    For families whose reference material is secret-bound
    (``requires_verifier_secret``, currently SYNTH-v0.1), a solver-usable
    challenge — including the public examples, whose expected outputs require
    the reference target — can only be assembled by an authority holding the
    verifier secret. Without it, only the public-generation part
    (``family.generate``) is produced. The challenge payload never carries the
    secret, the target, or the hidden tests; the authoritative verifier
    reinjects the secret at verification time.

    Challenge identity (SPEC "Challenge identity"): the canonical id covers
    ``(type, generator_version, seed, difficulty, payload)`` for ordinary
    families. Secret-bound families additionally commit to the verifier
    material: when *verifier_secret* is given, the full SHA-256
    ``verifier_material_commitment`` is computed here (never by the solver)
    and enters the identity, so same seed + different material =>
    different challenge_id.
    """
    family = get_family(type_name)
    commitment: str | None = None
    if getattr(family, "requires_verifier_secret", False):
        if verifier_secret is None:
            payload = family.generate(seed, difficulty)
        else:
            payload, _ = family.generate_with_solution(seed, difficulty, verifier_secret)
            commitment = verifier_material_commitment(verifier_secret)
    else:
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
    if commitment is not None:
        challenge_without_id["verifier_material_commitment"] = commitment
    return Challenge(
        id=stable_hash(challenge_without_id),
        type=family.type_name,
        generator_version=family.generator_version,
        seed=seed,
        difficulty=difficulty,
        payload=payload,
        verifier_material_commitment=commitment,
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