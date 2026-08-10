"""SYNTH-v0.1 challenge family registry."""

from vica.challenges.synth_v01.family import (
    DIFFICULTY_PRESETS,
    FAMILY,
    GENERATOR_VERSION,
    MAX_DIFFICULTY,
    TYPE_NAME,
    SynthV01,
    generate,
    generate_with_solution,
    hidden_tests_for,
)

__all__ = [
    "DIFFICULTY_PRESETS",
    "FAMILY",
    "GENERATOR_VERSION",
    "MAX_DIFFICULTY",
    "SynthV01",
    "TYPE_NAME",
    "generate",
    "generate_with_solution",
    "hidden_tests_for",
]
