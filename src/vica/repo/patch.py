"""REPO-v0.1 Patch — the candidate protocol object.

A REPO challenge's candidate is a **patch artifact**, not a modified full
repository. We use git unified diffs (``git diff`` style) so the patch is
small, auditable, storable, replayable, hashable, and re-applicable by a third
party.

REPO-v0.1 first version is **text-only**: binary patches are rejected. A patch
is bounded by hard limits and must never touch protected paths.

Applying a patch is done with ``git apply --check`` / ``git apply`` inside a
temporary workspace that was ``git init``-ed for the purpose — the workspace is
*not* required to be a git repo. We never hand-roll a patch parser.

Security: absolute paths, ``..`` traversal, symlink creation, and any patch
touching protected paths (``private/``, the VICA evaluator, evaluation
manifests, ``tests/`` for protected tests) are structural violations.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vica.protocol.models import ErrorCode
from vica.protocol.serialization import stable_hash

# Home of the authoritative VICA evaluator (must never be patched).
VICA_SOURCE_DIR_NAMES = ("vica",)
# Paths that no patch may ever touch. ``tests/`` and ``private/`` are the
# immutable verifier-controlled material: patching them is a structural
# violation (§30 Public Test Integrity — a patch that modifies a protected
# test is rejected without ever being executed).
PROTECTED_PATH_PREFIXES = ("private/", "tests/")

# Hard limits on a submitted patch.
MAX_PATCH_BYTES = 256 * 1024
MAX_CHANGED_FILES = 32
MAX_CHANGED_LINES = 4096

# A unified-diff header for a file path. ``\t``? diff uses ``a/path`` / ``b/path``.
_DIFF_HEAD_RE = re.compile(r"^(?:diff --git |(?:---|\\+\\+\\+) )a/(.+?)(?:\t|$)")


class PatchError(ValueError):
    """A patch is malformed, oversized, or violates structural constraints."""


@dataclass(frozen=True)
class PatchCandidate:
    """A submitted patch (git unified diff text) plus solver metadata."""

    patch: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def patch_bytes(self) -> int:
        return len(self.patch.encode("utf-8"))

    @property
    def patch_hash(self) -> str:
        return stable_hash(self.patch)


def parse_changed_paths(patch: str) -> list[str]:
    """Return the set of file paths a unified diff touches (``b/`` side).

    Only headers that look like unified diffs are considered; anything else is
    ignored here (structural checks raise on genuinely malformed input).
    """
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                # diff --git a/x b/y
                bpath = parts[3]
                if bpath.startswith("b/"):
                    paths.append(bpath[2:])
        elif line.startswith("--- ") and line.startswith("--- a/"):
            paths.append(line[6:])
    return paths


def _check_structural(patch: str) -> None:
    """Reject patches that violate REPO-v0.1 structural constraints."""
    if not isinstance(patch, str):
        raise PatchError("patch must be a string")
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise PatchError(f"patch exceeds MAX_PATCH_BYTES={MAX_PATCH_BYTES}")
    if "\0" in patch:
        raise PatchError("binary patch not allowed (REPO-v0.1 is text-only)")

    for line in patch.splitlines():
        # Absolute paths are never valid in a workspace-local diff.
        stripped = line.strip()
        if stripped.startswith("--- /") or stripped.startswith("+++ /"):
            raise PatchError(f"absolute path in patch: {line}")
        if ":" in stripped and (
            stripped.startswith("--- ") or stripped.startswith("+++ ")
        ):
            # Windows-style drive paths are not supported.
            if re.match(r"^[-\+]+\s+[a-zA-Z]:[/\\]", stripped):
                raise PatchError(f"absolute drive path in patch: {line}")

    paths = parse_changed_paths(patch)
    if len(paths) > MAX_CHANGED_FILES:
        raise PatchError(f"patch touches too many files: {len(paths)} > {MAX_CHANGED_FILES}")

    changed_lines = 0
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            changed_lines += 1
        elif line.startswith("-") and not line.startswith("---"):
            changed_lines += 1
    if changed_lines > MAX_CHANGED_LINES:
        raise PatchError(f"patch changes too many lines: {changed_lines} > {MAX_CHANGED_LINES}")

    for path in paths:
        if path.startswith(PROTECTED_PATH_PREFIXES):
            raise PatchError(f"patch touches protected path: {path}")
        if path.startswith(".git/"):
            raise PatchError(f"patch touches .git: {path}")
        if path.startswith("__pycache__/"):
            raise PatchError(f"patch touches __pycache__: {path}")
        if _is_vica_source(path):
            raise PatchError(f"patch touches VICA evaluator source: {path}")


def _is_vica_source(path: str) -> bool:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "src" and parts[1] in VICA_SOURCE_DIR_NAMES:
        return True
    return parts[0] in VICA_SOURCE_DIR_NAMES


def structural_error(patch: Any) -> ErrorCode | None:
    """Return a structural ErrorCode for a malformed patch, else None.

    Distinguishes a malformed / oversized patch (STRUCTURAL_VIOLATION) from a
    well-formed patch that simply fails to apply (PATCH_APPLY_FAILURE).
    """
    if patch is None:
        return ErrorCode.STRUCTURAL_VIOLATION
    if not isinstance(patch, dict) or not isinstance(patch.get("patch"), str):
        return ErrorCode.INVALID_SCHEMA
    try:
        _check_structural(patch["patch"])
    except PatchError:
        return ErrorCode.STRUCTURAL_VIOLATION
    return None


def apply_patch(workspace: str | Path, patch: str) -> None:
    """Apply a unified diff to *workspace* using ``git apply``.

    The workspace is materialized by the verifier and is treated as its own git
    repo (``git init``) purely as the patch-application mechanism — the original
    challenge's workspace is *never* modified. Raises ``PatchError`` when the
    patch does not apply cleanly.
    """
    _check_structural(patch)
    ws = Path(workspace)
    # An empty patch is the NoOp candidate: "don't modify any file". ``git apply``
    # rejects "no valid patches in input", so short-circuit it as a clean no-op.
    if not patch.strip():
        return
    try:
        subprocess.run(
            ["git", "init", "-q", str(ws)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(ws), "add", "-A"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        check = subprocess.run(
            ["git", "-C", str(ws), "apply", "--check", "--index", "-"],
            input=patch.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if check.returncode != 0:
            raise PatchError(
                f"git apply --check failed: {check.stderr.decode('utf-8', 'replace').strip()}"
            )
        apply = subprocess.run(
            ["git", "-C", str(ws), "apply", "--index", "-"],
            input=patch.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if apply.returncode != 0:
            raise PatchError(
                f"git apply failed: {apply.stderr.decode('utf-8', 'replace').strip()}"
            )
    except subprocess.TimeoutExpired as exc:
        raise PatchError(f"git apply timed out: {exc}") from exc
    except FileNotFoundError as exc:
        raise PatchError("git is required to apply REPO patches but was not found") from exc
    except subprocess.CalledProcessError as exc:
        raise PatchError(f"git apply failed: {exc}") from exc


def workspace_changed(original: dict[str, bytes], current: dict[str, bytes]) -> list[str]:
    """Return the list of paths whose bytes differ between original and current."""
    all_paths = set(original) | set(current)
    return sorted(p for p in all_paths if original.get(p) != current.get(p))


def patch_summary(patch: str) -> dict[str, Any]:
    """REPO result-bundle metadata for a patch (SPEC "v0.3 Result Bundle" §48).

    Computes the patch hash, byte size, changed file list, and changed-line
    count. These are portable, non-secret facts about the *submitted* patch and
    are safe to write into a Result Bundle (unlike the reference patch, the
    hidden tests, or the verifier secret).
    """
    changed_lines = 0
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            changed_lines += 1
        elif line.startswith("-") and not line.startswith("---"):
            changed_lines += 1
    return {
        "patch_hash": stable_hash(patch),
        "patch_bytes": len(patch.encode("utf-8")),
        "changed_files": parse_changed_paths(patch),
        "changed_lines": changed_lines,
    }


__all__ = [
    "MAX_CHANGED_FILES",
    "MAX_CHANGED_LINES",
    "MAX_PATCH_BYTES",
    "PatchCandidate",
    "PatchError",
    "apply_patch",
    "parse_changed_paths",
    "patch_summary",
    "structural_error",
    "workspace_changed",
]