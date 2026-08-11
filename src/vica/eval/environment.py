"""Environment / reproducibility metadata for Result Bundles."""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from vica import __version__


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def environment_manifest(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lightweight reproducibility manifest (never includes credentials)."""
    manifest: dict[str, Any] = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "vica_version": __version__,
        "git_commit": git_commit(),
    }
    try:
        import z3

        manifest["z3_version"] = z3.get_version_string()
    except Exception:  # pragma: no cover - optional dependency
        manifest["z3_version"] = None
    if extra:
        manifest.update(extra)
    return manifest


__all__ = ["environment_manifest", "git_commit"]