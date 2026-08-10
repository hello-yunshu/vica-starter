"""OS-level sandbox for executing untrusted candidate code (Milestone M9).

See :mod:`vica.sandbox.runner` for the implementation and platform notes.
"""

from vica.sandbox.runner import (
    SandboxError,
    SandboxLimits,
    SandboxResult,
    run_sandboxed,
)

__all__ = ["SandboxError", "SandboxLimits", "SandboxResult", "run_sandboxed"]