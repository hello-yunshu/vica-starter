"""Evaluation Bundle — M2 (docs/BENCHMARK_METHODOLOGY.md).

An Evaluation Bundle separates **public** solver material from **private**
verifier material so an external solver / coding agent can be handed only the
public part and any third party can later reverify the result.

Layout (logical, not mandatory names):

    <out>/
    ├── public/
    │   ├── manifest.json      # solver-visible metadata + challenges_hash
    │   ├── challenges.jsonl   # solver-visible Challenge objects (one per line)
    │   └── README.md
    └── private/
        ├── manifest.json      # verifier-material references + public hash link
        └── verifier-material.json  # evaluator secret (0600)

Integrity: the public/private manifests carry a ``manifest_hash`` that is the
SHA-256 of the same manifest **without** the ``manifest_hash`` field, using the
protocol's canonical serialization (never a raw ``json.dumps``). The public
manifest also carries ``challenges_hash`` (canonical hash of the challenge
list), so rewriting any challenge line is detected on inspect / verify.

Security boundary: this is **evaluator bundle organization**, not OS isolation.
A Coding Agent must be given only ``public/``, never the whole evaluation
directory (docs/BENCHMARK_METHODOLOGY.md "Security boundary").
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from vica import __version__
from vica.challenges.registry import available_types, build_challenge, get_family
from vica.eval.dispatch import check_evaluation_version
from vica.eval.models import BUNDLE_FORMAT_VERSION, BUNDLE_FORMAT_VERSION_V2, EvaluationFailure
from vica.protocol.serialization import canonical_json_bytes, stable_hash
from vica.repo.workspace import WorkspaceError, materialize_workspace
from vica.verifier.material import MATERIAL_VERSION, material_id, verifier_material_commitment

PUBLIC_DIR = "public"
PRIVATE_DIR = "private"
PUBLIC_MANIFEST = "manifest.json"
PUBLIC_CHALLENGES = "challenges.jsonl"
PUBLIC_README = "README.md"
PRIVATE_MANIFEST = "manifest.json"
PRIVATE_MATERIAL = "verifier-material.json"
# v2 Evaluation layout: solver-visible materialized REPO workspaces, one
# directory per challenge id (docs/SPEC.md "Evaluation Bundle Versioning").
PUBLIC_WORKSPACES_DIR = "workspaces"

# Hard limits on untrusted bundle inputs (docs/BENCHMARK_METHODOLOGY.md
# "Bundle size / input limits").
MAX_MANIFEST_BYTES = 1 << 20
MAX_CHALLENGE_LINE_BYTES = 1 << 20
MAX_CHALLENGES = 100_000


def _self_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of the manifest without its own ``manifest_hash`` field."""
    without = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    return stable_hash(without)


def _challenges_hash(challenge_dicts: list[dict[str, Any]]) -> str:
    return stable_hash(challenge_dicts)


def _bundle_version_for(challenge_type: str) -> str:
    """Evaluation layout version for a challenge type.

    The v2 layout is used for the REPO Workspace benchmark (its solver-visible
    workspaces are materialized as real files under ``public/workspaces/``).
    All other families keep the v1 layout; the dispatcher routes strictly by
    the advertised version.
    """
    from vica.repo.generator import TYPE_NAME as REPO_TYPE_NAME

    return BUNDLE_FORMAT_VERSION_V2 if challenge_type == REPO_TYPE_NAME else BUNDLE_FORMAT_VERSION


def prepare_evaluation(
    *,
    challenge_type: str,
    difficulties: list[int],
    instances: int,
    seed: int,
    out: str | Path,
    verifier_secret: str | None = None,
) -> dict[str, Any]:
    """Generate a public+private Evaluation Bundle into *out*.

    For secret-bound families (SYNTH-v0.1) a verifier secret is required to
    assemble solver-usable public examples. It is taken from
    ``VICA_VERIFIER_SECRET`` when set, else freshly generated and persisted in
    the private bundle. For ordinary families (CSP/OPT) no secret is used.
    Returns a summary dict (no secrets).

    The REPO Workspace benchmark (repo-v0.1) is written in the **v2** layout:
    each challenge's solver-visible workspace is additionally materialized as
    real files under ``public/workspaces/<challenge-id>/`` so a Coding Agent is
    handed a working directory, not an embedded payload.
    """
    if challenge_type not in available_types():
        raise ValueError(
            f"unknown challenge type {challenge_type!r}; available: {available_types()}"
        )
    if not difficulties:
        raise ValueError("at least one difficulty is required")
    if instances < 1:
        raise ValueError("instances must be >= 1")

    bundle_version = _bundle_version_for(challenge_type)
    family = get_family(challenge_type)
    is_secret = bool(getattr(family, "requires_verifier_secret", False))
    if is_secret:
        secret = verifier_secret or os.environ.get("VICA_VERIFIER_SECRET") or secrets.token_hex(32)
        commitment = verifier_material_commitment(secret)
    else:
        secret = None
        commitment = None
    secret_id = material_id(secret) if is_secret and secret is not None else None

    challenges: list[dict[str, Any]] = []
    for difficulty in sorted(set(difficulties)):
        for i in range(instances):
            cseed = f"{seed}:{difficulty}:{i}"
            ch = build_challenge(challenge_type, cseed, difficulty, verifier_secret=secret)
            challenges.append(ch.model_dump())

    challenges_hash = _challenges_hash(challenges)
    evaluation_id = _evaluation_id(
        challenge_type=challenge_type,
        generator_version=family.generator_version,
        difficulties=sorted(set(difficulties)),
        instances=instances,
        seed=seed,
        commitment=commitment,
        bundle_version=bundle_version,
    )

    public_manifest: dict[str, Any] = {
        "bundle_format_version": bundle_version,
        "evaluation_id": evaluation_id,
        "vica_version": __version__,
        "challenge_type": challenge_type,
        "generator_version": family.generator_version,
        "seed": seed,
        "difficulties": sorted(set(difficulties)),
        "instances_per_difficulty": instances,
        "challenge_count": len(challenges),
        "verifier_material_commitment": commitment,
        "verifier_material_version": MATERIAL_VERSION if is_secret else None,
        "challenges_hash": challenges_hash,
    }
    public_manifest["manifest_hash"] = _self_hash(public_manifest)

    private_manifest: dict[str, Any] = {
        "bundle_format_version": bundle_version,
        "evaluation_id": evaluation_id,
        "challenge_type": challenge_type,
        "generator_version": family.generator_version,
        "verifier_material_version": MATERIAL_VERSION if is_secret else None,
        "verifier_material_commitment": commitment,
        "verifier_material_id": secret_id,
        "public_manifest_hash": public_manifest["manifest_hash"],
        "challenges_hash": challenges_hash,
    }
    private_manifest["manifest_hash"] = _self_hash(private_manifest)

    out_path = Path(out)
    public_dir = out_path / PUBLIC_DIR
    private_dir = out_path / PRIVATE_DIR
    public_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)

    _write_json(public_dir / PUBLIC_MANIFEST, public_manifest)
    _write_jsonl(public_dir / PUBLIC_CHALLENGES, challenges)
    (public_dir / PUBLIC_README).write_text(_public_readme(public_manifest), encoding="utf-8")
    _write_json(private_dir / PRIVATE_MANIFEST, private_manifest)

    # v2 layout: materialize each REPO challenge's solver-visible workspace as
    # real files so an Agent is handed a working directory (not an embedded
    # payload). The write is authoritative: workspace_hash must match.
    if bundle_version == BUNDLE_FORMAT_VERSION_V2:
        _materialize_public_workspaces(public_dir, challenges)

    material = {
        "bundle_format_version": bundle_version,
        "evaluation_id": evaluation_id,
        "verifier_material_version": MATERIAL_VERSION if is_secret else None,
        "verifier_material_commitment": commitment,
        "verifier_material_id": secret_id,
        "verifier_secret": secret or "",
    }
    material_file = private_dir / PRIVATE_MATERIAL
    material_file.write_text(canonical_json_bytes(material).decode("utf-8"))
    try:
        material_file.chmod(0o600)
    except OSError:  # pragma: no cover - non-POSIX filesystems
        pass

    return {
        "evaluation_id": evaluation_id,
        "challenge_type": challenge_type,
        "challenge_count": len(challenges),
        "public_manifest_hash": public_manifest["manifest_hash"],
        "private_manifest_hash": private_manifest["manifest_hash"],
        "verifier_material_commitment": commitment,
        "out": str(out_path),
    }


def _evaluation_id(
    *,
    challenge_type: str,
    generator_version: str,
    difficulties: list[int],
    instances: int,
    seed: int,
    commitment: str | None,
    bundle_version: str,
) -> str:
    definition = {
        "bundle_format_version": bundle_version,
        "challenge_type": challenge_type,
        "generator_version": generator_version,
        "difficulties": difficulties,
        "instances_per_difficulty": instances,
        "seed": seed,
        "verifier_material_commitment": commitment,
    }
    return "eval-" + stable_hash(definition)[:12]


def _materialize_public_workspaces(
    public_dir: Path, challenges: list[dict[str, Any]]
) -> None:
    """Materialize each REPO challenge's workspace under ``public/workspaces/``.

    The manifest / files embedded in the challenge payload are written to real
    files so an Agent can operate on a directory. The authoritative
    ``workspace_hash`` is re-derived from the written files and must match the
    challenge's declared hash — a mismatch is an evaluator error (never a
    solver outcome).
    """
    from vica.repo.workspace import workspace_hash

    ws_root = public_dir / PUBLIC_WORKSPACES_DIR
    ws_root.mkdir(parents=True, exist_ok=True)
    for ch in challenges:
        payload = ch.get("payload")
        if not isinstance(payload, dict):
            continue
        manifest = payload.get("workspace_manifest")
        files = payload.get("workspace_files")
        if not isinstance(manifest, list) or not isinstance(files, dict):
            continue
        cid = str(ch.get("id", ""))
        if not cid:
            continue
        dest = ws_root / cid
        try:
            materialize_workspace(
                manifest,
                {k: _to_bytes(v) for k, v in files.items()},
                dest,
            )
        except WorkspaceError as exc:
            raise EvaluationFailure(
                f"cannot materialize public workspace for {cid}: {exc}"
            ) from exc
        declared = payload.get("workspace_hash")
        if isinstance(declared, str) and workspace_hash(dest) != declared:
            raise EvaluationFailure(
                f"public workspace {cid} does not match its declared workspace_hash"
            )


def _to_bytes(v: Any) -> bytes:
    if isinstance(v, bytes):
        return v
    return str(v).encode("utf-8")


def load_public_bundle(public_dir: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a *public* Evaluation Bundle directory directly as ``(manifest,
    challenges)``.

    This is the loader for the External Command Solver / File Exchange client:
    it consumes ``<evaluation>/public`` and never touches the private side.
    Unlike :func:`load_public_manifest` / :func:`load_public_challenges` (which
    take an evaluation *root* and resolve ``public/``), this takes the public
    directory itself. For convenience it also accepts an evaluation *root*
    (resolving ``public/``) so callers can pass either form.
    """
    root = Path(public_dir).resolve()
    public_dir = root / PUBLIC_DIR if (root / PUBLIC_DIR).is_dir() else root
    if not public_dir.is_dir():
        raise EvaluationFailure(f"missing public bundle directory {root}")
    manifest = _read_json(public_dir / PUBLIC_MANIFEST, max_bytes=MAX_MANIFEST_BYTES)
    _check_manifest_hash(manifest, "public manifest")
    check_evaluation_version(manifest.get("bundle_format_version"), "public manifest")
    challenges = _read_jsonl(public_dir / PUBLIC_CHALLENGES, MAX_CHALLENGES)
    if _challenges_hash(challenges) != manifest.get("challenges_hash"):
        raise EvaluationFailure(
            "public challenges.jsonl does not match public manifest challenges_hash "
            "(tampered or corrupted)"
        )
    _check_duplicate_ids(challenges)
    return manifest, challenges


def load_public_manifest(evaluation: str | Path) -> dict[str, Any]:
    """Load and integrity-check the public manifest of an evaluation bundle."""
    public_dir = _resolve_public_dir(evaluation)
    manifest = _read_json(public_dir / PUBLIC_MANIFEST, max_bytes=MAX_MANIFEST_BYTES)
    _check_manifest_hash(manifest, "public manifest")
    check_evaluation_version(manifest.get("bundle_format_version"), "public manifest")
    return manifest


def load_private_manifest(evaluation: str | Path) -> dict[str, Any]:
    private_dir = _resolve_private_dir(evaluation)
    manifest = _read_json(private_dir / PRIVATE_MANIFEST, max_bytes=MAX_MANIFEST_BYTES)
    _check_manifest_hash(manifest, "private manifest")
    check_evaluation_version(manifest.get("bundle_format_version"), "private manifest")
    return manifest


def load_verifier_material(evaluation: str | Path) -> dict[str, Any]:
    """Load the evaluator verifier material (contains the secret)."""
    private_dir = _resolve_private_dir(evaluation)
    material = _read_json(private_dir / PRIVATE_MATERIAL, max_bytes=MAX_MANIFEST_BYTES)
    return material


def load_public_challenges(evaluation: str | Path) -> list[dict[str, Any]]:
    """Load the solver-visible challenges and verify their hash against the
    public manifest (tamper detection)."""
    public_dir = _resolve_public_dir(evaluation)
    manifest = load_public_manifest(evaluation)
    challenges = _read_jsonl(public_dir / PUBLIC_CHALLENGES, MAX_CHALLENGES)
    if _challenges_hash(challenges) != manifest.get("challenges_hash"):
        raise EvaluationFailure(
            "public challenges.jsonl does not match public manifest challenges_hash "
            "(tampered or corrupted)"
        )
    _check_duplicate_ids(challenges)
    return challenges


def inspect_evaluation(evaluation: str | Path) -> dict[str, Any]:
    """Validate an Evaluation Bundle (no solver is invoked).

    ``vica eval inspect`` checks the whole bundle is usable for verification:
    manifest hashes, challenge hash, public/private consistency, generator
    version, and — for secret-bound families — that the private verifier
    material is present, parseable, supported, and its actual secret commits
    to the public commitment. Any failure sets ``status: FAIL`` (never an
    obscure traceback).
    """
    public_dir = _resolve_public_dir(evaluation)
    public_manifest = load_public_manifest(evaluation)
    private_manifest = load_private_manifest(evaluation)
    challenges = _read_jsonl(public_dir / PUBLIC_CHALLENGES, MAX_CHALLENGES)

    issues: list[str] = []
    if _challenges_hash(challenges) != public_manifest.get("challenges_hash"):
        issues.append("challenges.jsonl hash mismatch with public manifest")
    _check_duplicate_ids(challenges, issues=issues)
    if public_manifest.get("challenge_count") != len(challenges):
        issues.append(
            f"challenge_count {public_manifest.get('challenge_count')} != "
            f"actual {len(challenges)}"
        )
    if private_manifest.get("public_manifest_hash") != public_manifest.get("manifest_hash"):
        issues.append("private manifest does not reference this public manifest")
    if private_manifest.get("challenges_hash") != public_manifest.get("challenges_hash"):
        issues.append("private/public challenges_hash mismatch")

    commitment = public_manifest.get("verifier_material_commitment")
    challenge_type = public_manifest.get("challenge_type")
    generator_version = public_manifest.get("generator_version")
    for ch in challenges:
        if _commitment_str(ch.get("verifier_material_commitment")) != _commitment_str(
            commitment
        ):
            issues.append(f"challenge {ch.get('id')} has a different material commitment")
        if not isinstance(ch.get("id"), str) or not ch.get("id"):
            issues.append("challenge with missing/empty id")
        if ch.get("type") != challenge_type:
            issues.append(
                f"challenge {ch.get('id')} type {ch.get('type')!r} != manifest {challenge_type!r}"
            )
        if ch.get("generator_version") != generator_version:
            issues.append(
                f"challenge {ch.get('id')} generator_version {ch.get('generator_version')!r} "
                f"!= manifest {generator_version!r}"
            )

    # Generator version must be the one this build supports (exact-version-only).
    try:
        validate_generator_version(public_manifest, str(challenge_type), generator_version)
    except (EvaluationFailure, ValueError) as exc:
        issues.append(str(exc))

    # For secret-bound families the private material must be usable.
    try:
        material = load_verifier_material(evaluation)
    except EvaluationFailure as exc:
        issues.append(str(exc))
        material = {}
    try:
        validate_verifier_material(public_manifest, private_manifest, material)
    except EvaluationFailure as exc:
        issues.append(str(exc))

    return {
        "evaluation_id": public_manifest.get("evaluation_id"),
        "bundle_format_version": public_manifest.get("bundle_format_version"),
        "challenge_type": challenge_type,
        "generator_version": generator_version,
        "difficulties": public_manifest.get("difficulties"),
        "challenge_count": len(challenges),
        "public_manifest_hash": public_manifest.get("manifest_hash"),
        "private_manifest_hash": private_manifest.get("manifest_hash"),
        "verifier_material_commitment": commitment,
        "ok": not issues,
        "issues": issues,
    }


def _commitment_str(v: Any) -> str | None:
    return str(v) if v is not None else None


# ------------------------------------------------------------------ helpers


def _resolve_public_dir(evaluation: str | Path) -> Path:
    root = Path(evaluation).resolve()
    # Accept both an evaluation root (…/public) and a public dir directly.
    public_dir = root / PUBLIC_DIR if (root / PUBLIC_DIR).is_dir() else root
    if not public_dir.is_dir():
        raise EvaluationFailure(f"missing public directory in {root}")
    if not (public_dir / PUBLIC_MANIFEST).is_file():
        raise EvaluationFailure(f"missing public manifest in {public_dir}")
    return public_dir


def _resolve_private_dir(evaluation: str | Path) -> Path:
    root = Path(evaluation).resolve()
    private_dir = root / PRIVATE_DIR
    if not private_dir.is_dir():
        raise EvaluationFailure(f"missing private directory in {root}")
    return private_dir


def _check_manifest_hash(manifest: dict[str, Any], label: str) -> None:
    expected = manifest.get("manifest_hash")
    if not isinstance(expected, str):
        raise EvaluationFailure(f"{label} is missing manifest_hash")
    if _self_hash(manifest) != expected:
        raise EvaluationFailure(f"{label} manifest_hash mismatch (tampered or corrupted)")


def validate_verifier_material(
    public_manifest: dict[str, Any],
    private_manifest: dict[str, Any],
    material: dict[str, Any],
) -> None:
    """Validate that the private verifier material can authoritatively verify
    the public evaluation — before any solver is judged.

    For a secret-bound evaluation this enforces, in order:
        1. private manifest references this public manifest;
        2. private/public challenges_hash match;
        3. private manifest commitment == public commitment;
        4. material file declares a verifier secret;
        5. material version is supported;
        6. material-file declared commitment == public commitment;
        7. the commitment derived from the *actual* secret == public commitment.

    Any failure raises :class:`EvaluationFailure` (an evaluator configuration
    error, never a solver outcome). For non-secret-bound evaluations only the
    public/private cross-checks (1–3) apply.
    """
    if private_manifest.get("public_manifest_hash") != public_manifest.get("manifest_hash"):
        raise EvaluationFailure(
            "private bundle does not reference this public manifest (wrong private material)"
        )
    if private_manifest.get("challenges_hash") != public_manifest.get("challenges_hash"):
        raise EvaluationFailure("private/public challenges_hash mismatch")

    commitment = _commitment_str(public_manifest.get("verifier_material_commitment"))
    if commitment != _commitment_str(private_manifest.get("verifier_material_commitment")):
        raise EvaluationFailure(
            "verifier material commitment mismatch between public and private bundle "
            "(wrong or missing verifier material)"
        )

    if commitment is None:
        # Not secret-bound; nothing further to validate.
        return

    secret = material.get("verifier_secret")
    if not isinstance(secret, str) or not secret:
        raise EvaluationFailure(
            "secret-bound evaluation has no verifier secret in the private material"
        )

    material_version = material.get("verifier_material_version")
    if material_version != MATERIAL_VERSION:
        raise EvaluationFailure(
            f"unsupported verifier material version {material_version!r}; "
            f"supported: {MATERIAL_VERSION!r}"
        )

    if _commitment_str(material.get("verifier_material_commitment")) != commitment:
        raise EvaluationFailure(
            "verifier-material.json does not commit to the evaluation's material"
        )

    derived = verifier_material_commitment(secret)
    if derived != commitment:
        raise EvaluationFailure(
            "actual verifier secret does not match the evaluation's public commitment "
            "(wrong verifier material)"
        )


def validate_generator_version(
    manifest: dict[str, Any], challenge_type: str, generator_version: Any
) -> None:
    """Reject an evaluation whose generator version is not the one this build
    supports. v0.2 uses exact-version-only (no legacy generator dispatch)."""
    family = get_family(challenge_type)
    if generator_version != family.generator_version:
        raise EvaluationFailure(
            f"unsupported historical generator version {generator_version!r} for "
            f"{challenge_type!r}; supported: {family.generator_version!r}"
        )


def _check_duplicate_ids(challenges: list[dict[str, Any]], issues: list[str] | None = None) -> None:
    seen: set[str] = set()
    for ch in challenges:
        cid = ch.get("id")
        if not isinstance(cid, str):
            msg = f"challenge missing id: {cid!r}"
            if issues is not None:
                issues.append(msg)
            else:
                raise EvaluationFailure(msg)
            continue
        if cid in seen:
            msg = f"duplicate challenge id {cid!r} in public challenges"
            if issues is not None:
                issues.append(msg)
            else:
                raise EvaluationFailure(msg)
        seen.add(cid)


def _read_json(path: Path, max_bytes: int) -> dict[str, Any]:
    if not path.is_file():
        raise EvaluationFailure(f"missing file {path}")
    if path.stat().st_size > max_bytes:
        raise EvaluationFailure(f"file too large: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise EvaluationFailure(f"cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvaluationFailure(f"{path} is not a JSON object")
    return data


def _read_jsonl(path: Path, max_lines: int) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvaluationFailure(f"missing file {path}")
    result: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if len(line.encode("utf-8")) > MAX_CHALLENGE_LINE_BYTES:
                raise EvaluationFailure(f"line {line_no} of {path} is too large")
            if line_no > max_lines:
                raise EvaluationFailure(f"{path} has too many lines")
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise EvaluationFailure(f"invalid JSON on line {line_no} of {path}: {exc}") from exc
            if not isinstance(obj, dict):
                raise EvaluationFailure(f"line {line_no} of {path} is not an object")
            result.append(obj)
    return result


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(canonical_json_bytes(obj).decode("utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(canonical_json_bytes(row).decode("utf-8") + "\n")


def _public_readme(manifest: dict[str, Any]) -> str:
    commitment = manifest.get("verifier_material_commitment")
    secret_note = (
        "This evaluation is verifier-material-bound: challenges carry a public\n"
        "SHA-256 commitment of the verifier material. The reference target and\n"
        "hidden tests are NOT in this bundle and are only derivable by the\n"
        "evaluator who holds the material."
        if commitment
        else "This evaluation is not verifier-material-bound (no hidden material)."
    )
    return (
        "# Evaluation Bundle\n\n"
        f"evaluation_id: {manifest.get('evaluation_id')}\n"
        f"challenge_type: {manifest.get('challenge_type')}\n"
        f"generator_version: {manifest.get('generator_version')}\n"
        f"challenge_count: {manifest.get('challenge_count')}\n\n"
        "This is the PUBLIC part of an evaluation bundle. It contains only the\n"
        "solver-visible challenges. It must be the ONLY material handed to an\n"
        "external solver / coding agent.\n\n"
        f"{secret_note}\n\n"
        "Submit answers as a Submission Bundle (see docs/protocol/BUNDLE.md):\n"
        "a manifest.json plus a submissions.jsonl with one line per challenge:\n\n"
        '    {"challenge_id": "...", "candidate": {...}, "metadata": {...}}\n'
    )


__all__ = [
    "PRIVATE_MATERIAL",
    "inspect_evaluation",
    "load_private_manifest",
    "load_public_bundle",
    "load_public_challenges",
    "load_public_manifest",
    "load_verifier_material",
    "prepare_evaluation",
    "validate_generator_version",
    "validate_verifier_material",
]