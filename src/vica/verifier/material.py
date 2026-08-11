"""Verifier material commitment (SPEC v0.1 "Challenge identity").

Secret-bound challenge families (currently SYNTH-v0.1) derive their reference
target and hidden tests from an evaluator-held verifier secret. The public
Challenge carries a one-way commitment of that material so that:

- the challenge identity binds the material (same seed + different material =>
  different challenge_id),
- the authoritative verifier can reject a wrong/missing secret as an
  evaluator configuration failure (INTERNAL_ERROR) instead of misreporting a
  solver error.

The commitment is public and must never be used as the secret itself: it is
SHA-256 over a domain-separated string including the material version, so a
solver holding the commitment cannot invert it to the secret.
"""

from __future__ import annotations

import hashlib

# Version of the secret -> material derivation scheme. Bumping it invalidates
# all existing commitments (same secret, new version => different commitment),
# which is the intended signal when the derivation scheme changes.
MATERIAL_VERSION = "synth-v0.1-hmac-sha256-target-hidden:v1"

# Domain separation tag: distinguishes this hash from every other hash in the
# protocol (stable_hash, HMAC target/hidden streams, ...).
COMMITMENT_DOMAIN = "vica:verifier-material"


def verifier_material_commitment(verifier_secret: str) -> str:
    """Full SHA-256 commitment (64 hex chars) of the verifier material.

    ``SHA256("vica:verifier-material:" + MATERIAL_VERSION + ":" + secret)``.
    Deterministic for a fixed (version, secret); the full digest is the
    protocol commitment — never truncate it for identity decisions.
    """
    return hashlib.sha256(
        f"{COMMITMENT_DOMAIN}:{MATERIAL_VERSION}:{verifier_secret}".encode()
    ).hexdigest()


def material_id(verifier_secret: str) -> str:
    """Short human/database display id derived from the commitment.

    Display only: identity binding always uses the full commitment.
    """
    return verifier_material_commitment(verifier_secret)[:16]


__all__ = [
    "COMMITMENT_DOMAIN",
    "MATERIAL_VERSION",
    "material_id",
    "verifier_material_commitment",
]
