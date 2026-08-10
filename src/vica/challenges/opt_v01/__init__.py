"""OPT-v0.1 challenge family registry."""

from vica.challenges.opt_v01.family import (
    DIFFICULTY_PRESETS,
    FAMILY,
    GENERATOR_VERSION,
    MAX_DIFFICULTY,
    TYPE_NAME,
    OptV01,
    generate,
    score_order,
)

__all__ = [
    "DIFFICULTY_PRESETS",
    "FAMILY",
    "GENERATOR_VERSION",
    "MAX_DIFFICULTY",
    "OptV01",
    "TYPE_NAME",
    "generate",
    "score_order",
]