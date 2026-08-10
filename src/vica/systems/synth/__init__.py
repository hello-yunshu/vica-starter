"""SYNTH-v0.1 participant systems (non-AI baselines).

Required by AGENTS.md invariant #5: every challenge has a traditional/non-AI
baseline. These two systems never call an LLM.
"""

from vica.systems.synth.brute_force import BruteForceSynthSystem
from vica.systems.synth.random_program import RandomProgramSystem

__all__ = [
    "BruteForceSynthSystem",
    "RandomProgramSystem",
]
