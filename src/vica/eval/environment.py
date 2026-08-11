"""Environment / reproducibility metadata for Result Bundles.

v0.2 defined a lightweight ``environment_manifest`` (OS / python / vica version /
git commit) embedded in every Result Bundle. v0.4 adds an explicit
``ExecutionProfile`` (docs/REPRODUCIBILITY.md): the runner backend, OS/arch,
Python, a dependency environment hash, and the *policy* of an execution
(timeout, CPU/memory budget, network policy, forwarded env *names* — never
values — and the agent command identity).

Secret policy (§64): a profile may record that ``OPENAI_API_KEY`` was
``supplied``, but never the value; verifier-reserved secrets are never
recorded at all.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from typing import Any

from vica import __version__

# Dependency names whose installed versions shape reproducibility. We hash the
# *installed* version of the package itself plus a few environment-defining
# deps, never credentials.
_PROVENANCE_PACKAGES = ("vica", "pydantic", "typer")


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


def dependency_environment_hash() -> str:
    """A stable hash of installed provenance-relevant package versions.

    Captures the interpreter + the installed versions of VICA and its core
    dependencies. Two environments with different dependency sets produce a
    different hash, so a Result Bundle's provenance reveals whether it was
    produced under the same dependency environment. Never includes credentials.
    """
    parts: dict[str, str] = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
    }
    for name in _PROVENANCE_PACKAGES:
        parts[name] = _installed_version(name)
    return hashlib.sha256(
        "\n".join(f"{k}={v}" for k, v in sorted(parts.items())).encode("utf-8")
    ).hexdigest()


def _installed_version(name: str) -> str:
    try:
        import importlib.metadata as md

        return md.version(name) or ""
    except Exception:  # pragma: no cover - optional / not installed
        return ""


def execution_profile(
    *,
    backend: str = "local",
    timeout_s: float | None = None,
    cpu_budget: str | None = None,
    memory_budget: str | None = None,
    network_policy: str = "default",
    passed_env_names: list[str] | None = None,
    agent_command: str | None = None,
) -> dict[str, Any]:
    """Build an ExecutionProfile for a run.

    ``passed_env_names`` records only the *names* a user explicitly forwarded
    (never the values). ``agent_command`` is the command identity for a Coding
    Agent run. Callers pass the fields they know; unspecified policy fields stay
    ``None`` so an honest profile does not invent budgets it did not set.
    """
    profile: dict[str, Any] = {
        "runner_backend": backend,
        "os": platform.system(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "dependency_environment_hash": dependency_environment_hash(),
        "vica_version": __version__,
        "git_commit": git_commit(),
        "network_policy": network_policy,
        "timeout_s": timeout_s,
        "cpu_budget": cpu_budget,
        "memory_budget": memory_budget,
        "passed_env_names": sorted(
            {str(n) for n in (passed_env_names or []) if _safe_env_name(str(n))}
        ),
        "agent_command": agent_command,
    }
    return profile


def _safe_env_name(name: str) -> bool:
    """An env name is only recorded if it is not a verifier-reserved secret."""
    return not (name.startswith("VICA_VERIFIER_SECRET") or name.startswith("VICA_PRIVATE_"))


def environment_manifest(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lightweight reproducibility manifest (never includes credentials).

    Composes the base environment facts with a ``profile`` sub-object carrying
    the ExecutionProfile fields supplied by the caller, plus the dependency
    environment hash.
    """
    manifest: dict[str, Any] = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "vica_version": __version__,
        "git_commit": git_commit(),
        "dependency_environment_hash": dependency_environment_hash(),
    }
    try:
        import z3

        manifest["z3_version"] = z3.get_version_string()
    except Exception:  # pragma: no cover - optional dependency
        manifest["z3_version"] = None
    if extra:
        manifest.update(extra)
    return manifest


__all__ = [
    "dependency_environment_hash",
    "environment_manifest",
    "execution_profile",
    "git_commit",
]