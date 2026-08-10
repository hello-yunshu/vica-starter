"""VICA deterministic verifier service."""

from vica.verifier.interfaces import ChallengeFamily, SolverSystem, Verifier
from vica.verifier.verifier import verify_submission

__all__ = ["ChallengeFamily", "SolverSystem", "Verifier", "verify_submission"]