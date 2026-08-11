"""SYNTH-v0.1 challenge family registry.

Public solver-facing API: ``FAMILY``, ``TYPE_NAME``, ``GENERATOR_VERSION``,
the difficulty presets, ``generate``, and the DSL helpers — these are listed
in ``__all__``.

Verifier/calibration-only helpers (``generate_with_solution``,
``hidden_tests_for``, ``VERIFIER_SECRET_KEY``) stay importable for the
authoritative verifier, tests, and calibration tooling, but are intentionally
excluded from ``__all__``: a solver workspace must not rely on them, and
without the verifier secret they cannot produce reference material anyway
(see docs/SPEC.md "Verifier material" and the Evaluation Mode boundary).
"""

from vica.challenges.synth_v01.family import (
    DIFFICULTY_PRESETS,
    FAMILY,
    GENERATOR_VERSION,
    MAX_DIFFICULTY,
    TYPE_NAME,
    VERIFIER_SECRET_KEY,  # noqa: F401  (verifier-only key name)
    SynthV01,
    eval_program,
    generate,
    generate_with_solution,  # noqa: F401  (verifier/calibration-only helper)
    hidden_tests_for,  # noqa: F401  (verifier/calibration-only helper)
    parse_program,
    program_to_source,
    public_tests_ok,
    sample_program,
    token_count,
)

__all__ = [
    "DIFFICULTY_PRESETS",
    "FAMILY",
    "GENERATOR_VERSION",
    "MAX_DIFFICULTY",
    "SynthV01",
    "TYPE_NAME",
    "eval_program",
    "generate",
    "parse_program",
    "program_to_source",
    "public_tests_ok",
    "sample_program",
    "token_count",
]