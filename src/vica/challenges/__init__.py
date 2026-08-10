"""Challenge families registry."""

from vica.challenges.registry import (
    available_types,
    build_challenge,
    get_family,
    register,
    verify_candidate,
)

__all__ = [
    "available_types",
    "build_challenge",
    "get_family",
    "register",
    "verify_candidate",
]