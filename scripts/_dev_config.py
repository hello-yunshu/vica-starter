"""Shared verifier secret for local dev/calibration tooling.

NON-SECRET, DEV ONLY -- NEVER FOR ADVERSARIAL EVALUATION.
A deterministic default keeps dev scripts reproducible; set
``VICA_DEV_VERIFIER_SECRET`` to override. Real evaluations must use the
evaluator-provided secret via the verifier-private path (``.vica/private/``),
never this value, and must not expose secret-bound material to a solver
workspace.
"""

from __future__ import annotations

import os

VERIFIER_SECRET = os.environ.get("VICA_DEV_VERIFIER_SECRET") or "dev-script-verifier-secret"