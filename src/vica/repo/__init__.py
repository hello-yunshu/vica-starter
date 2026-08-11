"""REPO-v0.1 — code-repository challenge infrastructure.

A REPO challenge presents a small Python source workspace plus a task; the
candidate is a git unified-diff patch. This package provides:

- :mod:`vica.repo.workspace` — workspace manifest, identity hash, safety.
- :mod:`vica.repo.patch`    — the Patch candidate protocol object + apply.
- :mod:`vica.repo.templates` — the v0.3 task templates (deterministic repos).
- :mod:`vica.repo.generator` — the REPO-v0.1 generator (workspace + reference
  patch + hidden material), secret-bound like SYNTH-v0.1.
- :mod:`vica.repo.family`   — the authoritative REPO ChallengeFamily.
"""

from __future__ import annotations

from vica.repo.workspace import (
    EXCLUDED_DIRS,
    WorkspaceError,
    materialize_workspace,
    workspace_hash,
    workspace_manifest,
)

__all__ = [
    "EXCLUDED_DIRS",
    "WorkspaceError",
    "materialize_workspace",
    "workspace_hash",
    "workspace_manifest",
]