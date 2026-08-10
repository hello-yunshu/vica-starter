"""OPT-v0.1 participant systems (non-AI baselines).

Required by AGENTS.md invariant #5: every challenge has a traditional/non-AI
baseline. None of these call an LLM.
"""

from vica.systems.opt.brute import BruteOptSystem
from vica.systems.opt.dp import DpOptSystem
from vica.systems.opt.edd import EddSystem
from vica.systems.opt.random_order import RandomOrderSystem

__all__ = [
    "BruteOptSystem",
    "DpOptSystem",
    "EddSystem",
    "RandomOrderSystem",
]