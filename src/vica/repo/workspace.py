"""REPO-v0.1 Workspace — manifest, identity hash, and safety.

A *workspace* is a small Python / UTF-8 text repository that a REPO challenge
presents to an Agent. Its stable identity must not depend on directory name,
mtime, or filesystem order, so we define a canonical workspace manifest:

    workspace_manifest = sorted([{relative_path, sha256, mode}, ...])

just over **regular files**. Directories are reconstructed on materialize and
are not hashed (they carry no content). The identity is:

    workspace_hash = SHA-256(canonical_json(sorted(manifest)))

``relative_path`` is always a POSIX-style relative path (``/`` separator),
never absolute, never containing ``..``, and never a symlink target escape.

Safety (v0.3 first version): only regular files and directories are allowed.
Everything else — symlinks, FIFOs, sockets, device files, embedded ``.git`` —
is rejected. The following generated/excluded directories are always skipped:

    .git/ __pycache__/ .pytest_cache/ .mypy_cache/ .ruff_cache/ .vica/
    build/ dist/

See docs/challenge-research/repo/threat-model.md.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from vica.protocol.serialization import canonical_json_bytes

# Directories that must never be part of a workspace identity / payload.
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".vica",
        "build",
        "dist",
    }
)

# A workspace file may at most be this large; larger files are rejected.
MAX_WORKSPACE_FILE_BYTES = 1 << 20
# A single workspace may contain at most this many files.
MAX_WORKSPACE_FILES = 4096


class WorkspaceError(ValueError):
    """A workspace is unsafe, malformed, or its identity is inconsistent."""


def _is_excluded(rel: PurePosixPath) -> bool:
    return any(part in EXCLUDED_DIRS for part in rel.parts)


def _check_rel_path(rel: PurePosixPath) -> None:
    if not rel.parts:
        raise WorkspaceError("empty workspace path")
    if rel.is_absolute():
        raise WorkspaceError(f"absolute workspace path not allowed: {rel}")
    if ".." in rel.parts:
        raise WorkspaceError(f"path traversal not allowed: {rel}")
    if "." in rel.parts:
        raise WorkspaceError(f"non-canonical path not allowed: {rel}")
    if _is_excluded(rel):
        raise WorkspaceError(f"excluded directory in workspace path: {rel}")


def _dir_entries(root: Path) -> list[Path]:
    """Yield every regular file under *root* with POSIX relative names.

    Walks the tree, skipping excluded directories and rejecting any non-regular
    file (symlink, FIFO, socket, device) as a safety violation.
    """
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dpath = Path(dirpath)
        # Skip excluded directories in place (never descend into them).
        kept: list[str] = []
        for d in dirnames:
            if d == ".git":
                # A root ``.git`` is the workspace's own repo dir and is excluded
                # from the identity (§11); a *nested* ``.git`` signals an embedded
                # repo/submodule and is rejected (§12).
                if dpath != root:
                    raise WorkspaceError(f"embedded .git directory not allowed: {dpath / d}")
                continue
            if d in EXCLUDED_DIRS:
                continue
            kept.append(d)
        dirnames[:] = kept
        for name in filenames:
            fp = dpath / name
            mode = fp.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise WorkspaceError(f"symlink not allowed in workspace: {fp}")
            if not stat.S_ISREG(mode):
                raise WorkspaceError(f"non-regular file not allowed in workspace: {fp}")
            files.append(fp)
    return files


def workspace_manifest(root: str | Path) -> list[dict[str, Any]]:
    """Return the canonical workspace manifest (sorted regular-file entries).

    Each entry is ``{"path": <posix rel>, "sha256": <hex>, "mode": <str>}`` where
    ``mode`` keeps only the executable bit (``0o755`` vs ``0o644``) — the only
    mode semantics REPO-v0.1 needs.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise WorkspaceError(f"workspace is not a directory: {root}")
    entries: list[dict[str, Any]] = []
    for fp in _dir_entries(root):
        rel = PurePosixPath(fp.relative_to(root).as_posix())
        _check_rel_path(rel)
        size = fp.stat().st_size
        if size > MAX_WORKSPACE_FILE_BYTES:
            raise WorkspaceError(f"workspace file too large: {rel}")
        digest = hashlib.sha256(fp.read_bytes()).hexdigest()
        mode = fp.stat().st_mode
        mode_str = "755" if mode & 0o111 else "644"
        entries.append({"path": rel.as_posix(), "sha256": digest, "mode": mode_str})
    if len(entries) > MAX_WORKSPACE_FILES:
        raise WorkspaceError(f"workspace has too many files: {len(entries)}")
    entries.sort(key=lambda e: e["path"])
    return entries


def workspace_hash(root: str | Path) -> str:
    """SHA-256 identity of a workspace directory (see module docstring)."""
    manifest = workspace_manifest(root)
    return hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()


def manifest_hash(manifest: list[dict[str, Any]]) -> str:
    """Compute the workspace hash from an already-sorted manifest."""
    return hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()


def validate_manifest(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalize a parsed workspace manifest.

    Enforces sorted POSIX relative paths, no duplicates, no traversal, and
    well-formed hashes/modes. Returns the normalized manifest.
    """
    if not isinstance(manifest, list):
        raise WorkspaceError("workspace manifest must be a list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in manifest:
        if not isinstance(entry, dict):
            raise WorkspaceError("workspace manifest entry must be an object")
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel:
            raise WorkspaceError("workspace manifest entry missing path")
        pure = PurePosixPath(rel)
        _check_rel_path(pure)
        if rel in seen:
            raise WorkspaceError(f"duplicate workspace path: {rel}")
        seen.add(rel)
        digest = entry.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise WorkspaceError(f"malformed sha256 for {rel!r}")
        mode = entry.get("mode")
        if mode not in ("644", "755"):
            raise WorkspaceError(f"unsupported mode {mode!r} for {rel!r}")
        normalized.append({"path": rel, "sha256": digest, "mode": mode})
    normalized.sort(key=lambda e: e["path"])
    return normalized


def materialize_workspace(
    manifest: list[dict[str, Any]],
    files: dict[str, bytes],
    dest: str | Path,
) -> Path:
    """Materialize a workspace manifest + file bytes into *dest*.

    The manifest is validated and every required file must be present with a
    matching SHA-256. The destination is created (and must not already exist as
    a file). This is the *authoritative* reconstruction used by the verifier
    before applying a patch.
    """
    manifest = validate_manifest(manifest)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for entry in manifest:
        rel = PurePosixPath(entry["path"])
        target = dest.joinpath(*rel.parts)
        data = files.get(rel.as_posix())
        if data is None:
            raise WorkspaceError(f"missing file in materialize: {rel}")
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise WorkspaceError(f"file content does not match manifest: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if entry["mode"] == "755":
            target.chmod(0o755)
        else:
            target.chmod(0o644)
    return dest


def read_workspace_files(root: str | Path) -> dict[str, bytes]:
    """Read every regular file of a workspace into ``{posix_path: bytes}``."""
    root = Path(root).resolve()
    result: dict[str, bytes] = {}
    for fp in _dir_entries(root):
        rel = PurePosixPath(fp.relative_to(root).as_posix())
        result[rel.as_posix()] = fp.read_bytes()
    return result


__all__ = [
    "EXCLUDED_DIRS",
    "MAX_WORKSPACE_FILE_BYTES",
    "MAX_WORKSPACE_FILES",
    "WorkspaceError",
    "manifest_hash",
    "materialize_workspace",
    "read_workspace_files",
    "validate_manifest",
    "workspace_hash",
    "workspace_manifest",
]