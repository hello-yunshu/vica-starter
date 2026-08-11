"""Authoritative verification and Result Bundle — M4.

``vica eval verify`` reuses the single authoritative ``verify_submission``
from ``vica.verifier.verifier`` — there is no second verifier. It:

1. loads and hash-validates the public manifest & challenges;
2. loads and hash-validates the private manifest & verifier material;
3. cross-checks public/private consistency and the material commitment
   (a wrong private bundle is an Evaluation Failure, never a solver failure);
4. matches each submission challenge_id, reconstructs the Challenge, and runs
   ``verify_submission`` with the evaluator secret;
5. records raw results (missing challenges -> NO_SUBMISSION), computes metrics,
   and writes a portable Result Bundle.

A Result Bundle never contains the verifier secret, hidden tests, or the
reference target; its manifest carries per-file SHA-256 hashes plus a bundle
hash so modification is detected (docs/BENCHMARK_METHODOLOGY.md).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vica import __version__
from vica.eval.bundle import (
    load_private_manifest,
    load_public_challenges,
    load_public_manifest,
    load_verifier_material,
    validate_generator_version,
    validate_verifier_material,
)
from vica.eval.environment import environment_manifest, git_commit
from vica.eval.metrics import summarize
from vica.eval.models import (
    RESULT_BUNDLE_VERSION,
    EvaluationFailure,
    ReportStatus,
    ResultRecord,
    to_result_record,
)
from vica.eval.report import render_report
from vica.eval.submission import load_submission_bundle
from vica.protocol.models import CandidateSubmission, Challenge
from vica.protocol.serialization import canonical_json_bytes, stable_hash
from vica.verifier.verifier import verify_submission

# Fixed set of file names a Result Bundle v1 may contain (docs/BENCHMARK_METHODOLOGY.md).
RESULT_FILE_ALLOWLIST = (
    "manifest.json",
    "evaluation.json",
    "system.json",
    "environment.json",
    "challenges.jsonl",
    "submissions.jsonl",
    "results.jsonl",
    "metrics.json",
    "report.md",
)
MAX_RESULT_FILE_BYTES = 64 << 20


def verify_evaluation(
    *,
    evaluation: str | Path,
    submission: str | Path,
    out: str | Path,
    system_id: str | None = None,
) -> dict[str, Any]:
    """Authoritatively verify a Submission Bundle against an Evaluation and
    write a Result Bundle to *out*. Returns a summary (no secrets)."""
    public_manifest = load_public_manifest(evaluation)
    private_manifest = load_private_manifest(evaluation)
    material = load_verifier_material(evaluation)
    challenges = load_public_challenges(evaluation)

    # Fail fast on wrong/missing verifier material BEFORE any candidate is
    # judged — a wrong secret is an evaluator error, never N x INTERNAL_ERROR.
    validate_verifier_material(public_manifest, private_manifest, material)

    # Exact-version-only generator compatibility (reproducibility).
    challenge_type = public_manifest.get("challenge_type")
    generator_version = public_manifest.get("generator_version")
    validate_generator_version(public_manifest, str(challenge_type), generator_version)
    _check_challenge_rows(challenges, challenge_type, generator_version)

    sub_manifest, rows = load_submission_bundle(submission, evaluation)
    if system_id is None:
        _system = sub_manifest.get("system_id")
        if not isinstance(_system, str) or not _system:
            raise EvaluationFailure("submission bundle has no system_id; pass --system")
        system_id = _system

    submitted = {row["challenge_id"]: row for row in rows}
    verifier_secret = material.get("verifier_secret") or None

    results: list[ResultRecord] = []
    for ch in challenges:
        cid = ch["id"]
        row = submitted.get(cid)
        if row is None:
            results.append(
                to_result_record(
                    cid,
                    ch.get("type", ""),
                    str(ch.get("generator_version", "")),
                    int(ch.get("difficulty", 0)),
                    str(ch.get("seed", "")),
                    system_id,
                    valid=False,
                    score=0.0,
                    error_code=None,
                    status=ReportStatus.NO_SUBMISSION,
                    metadata={"status": ReportStatus.NO_SUBMISSION.value},
                )
            )
            continue
        results.append(
            _verify_one(
                ch, row.get("candidate"), row.get("metadata") or {}, system_id, verifier_secret
            )
        )

    return _write_result_bundle(
        public_manifest=public_manifest,
        challenges=challenges,
        sub_manifest=sub_manifest,
        results=results,
        out=out,
        system_id=system_id,
    )


def _check_challenge_rows(
    challenges: list[dict[str, Any]], challenge_type: Any, generator_version: Any
) -> None:
    """Every challenge row must agree with the evaluation manifest."""
    for ch in challenges:
        if ch.get("type") != challenge_type:
            raise EvaluationFailure(
                f"challenge {ch.get('id')} type {ch.get('type')!r} != manifest "
                f"{challenge_type!r}"
            )
        if ch.get("generator_version") != generator_version:
            raise EvaluationFailure(
                f"challenge {ch.get('id')} generator_version {ch.get('generator_version')!r} "
                f"!= manifest {generator_version!r}"
            )


# Map a command-solver ``_vica_runner.solver_status`` to a report status.
# These are solver outcomes (no candidate was produced), never NO_SUBMISSION and
# never a call to the challenge verifier.
_SOLVER_STATUS_MAP: dict[str, ReportStatus] = {
    "timeout": ReportStatus.TIMEOUT,
    "parse_error": ReportStatus.PARSE_ERROR,
    "wrong_challenge_id": ReportStatus.PARSE_ERROR,
    "no_candidate": ReportStatus.NO_CANDIDATE,
    "nonzero_exit": ReportStatus.NO_CANDIDATE,
    "output_too_large": ReportStatus.SANDBOX_ERROR,
    "sandbox_error": ReportStatus.SANDBOX_ERROR,
    "spawn_error": ReportStatus.SANDBOX_ERROR,
}


def _runner_telemetry(metadata: dict[str, Any]) -> dict[str, Any]:
    """Read VICA-owned runner telemetry under the reserved ``_vica_runner`` key.

    Only this key is trusted for latency; a solver-supplied ``metadata.wall_time_ms``
    is not trusted telemetry.
    """
    runner = metadata.get("_vica_runner")
    return runner if isinstance(runner, dict) else {}


def _verify_one(
    ch: dict[str, Any],
    candidate: Any,
    metadata: dict[str, Any],
    system_id: str,
    verifier_secret: str | None,
) -> ResultRecord:
    runner = _runner_telemetry(metadata)
    solve_wall_time_ms = _as_float(runner.get("wall_time_ms"))
    solver_status = runner.get("solver_status")

    # A command-solver failure has no candidate; record its outcome directly
    # without invoking the challenge verifier.
    if candidate is None and solver_status is not None:
        status = _SOLVER_STATUS_MAP.get(str(solver_status), ReportStatus.NO_CANDIDATE)
        return to_result_record(
            challenge_id=str(ch.get("id", "")),
            challenge_type=ch.get("type", ""),
            generator_version=str(ch.get("generator_version", "")),
            difficulty=int(ch.get("difficulty", 0)),
            seed=str(ch.get("seed", "")),
            system_id=system_id,
            valid=False,
            score=0.0,
            error_code=None,
            solve_wall_time_ms=solve_wall_time_ms,
            status=status,
            metadata=dict(metadata),
        )

    challenge = Challenge.model_validate(ch)
    submission = CandidateSubmission(
        challenge_id=challenge.id,
        system_id=system_id,
        candidate=candidate,
        metadata=metadata,
    )
    result = verify_submission(challenge, submission, verifier_secret=verifier_secret)
    meta = dict(metadata)
    if ch.get("type") == "opt-v0.1" and result.valid:
        optimal = _opt_optimal_score(ch)
        if optimal is not None:
            meta["optimal_score"] = optimal
            meta["regret"] = optimal - result.score
    return to_result_record(
        challenge_id=challenge.id,
        challenge_type=ch.get("type", ""),
        generator_version=str(ch.get("generator_version", "")),
        difficulty=int(ch.get("difficulty", 0)),
        seed=str(ch.get("seed", "")),
        system_id=system_id,
        valid=result.valid,
        score=result.score,
        error_code=result.error_code,
        solve_wall_time_ms=solve_wall_time_ms,
        verify_time_us=result.verify_time_us,
        candidate=candidate,
        metadata=meta,
    )


def _as_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _opt_optimal_score(ch: dict[str, Any]) -> float | None:
    """Exact optimal score for an OPT-v0.1 payload (bitmask DP reference)."""
    try:
        from vica.challenges.opt_v01.family import score_order
        from vica.systems.opt.dp import optimal_order

        payload = ch.get("payload") or {}
        processing = payload.get("processing")
        deadlines = payload.get("deadlines")
        if not isinstance(processing, list) or not isinstance(deadlines, list):
            return None
        return float(score_order(processing, deadlines, optimal_order(processing, deadlines)))
    except Exception:  # pragma: no cover - defensive
        return None


# ------------------------------------------------------------------ result bundle


def _write_result_bundle(
    *,
    public_manifest: dict[str, Any],
    challenges: list[dict[str, Any]],
    sub_manifest: dict[str, Any],
    results: list[ResultRecord],
    out: str | Path,
    system_id: str,
) -> dict[str, Any]:
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)

    submission_rows = [
        {
            "challenge_id": r.challenge_id,
            "candidate": r.candidate,
            "metadata": r.metadata,
        }
        for r in results
        if r.status != ReportStatus.NO_SUBMISSION
    ]

    files: dict[str, bytes] = {
        "evaluation.json": canonical_json_bytes(public_manifest),
        "system.json": canonical_json_bytes(sub_manifest),
        "environment.json": canonical_json_bytes(environment_manifest()),
        "challenges.jsonl": _jsonl_bytes(challenges),
        "submissions.jsonl": _jsonl_bytes(submission_rows),
        "results.jsonl": _jsonl_bytes([r.__dict__ for r in results]),
        "metrics.json": canonical_json_bytes(summarize(results)),
        "report.md": render_report(
            evaluation=public_manifest,
            system_id=system_id,
            results=results,
            git_commit=git_commit(),
        ).encode("utf-8"),
    }

    file_hashes = {
        name: "sha256:" + hashlib.sha256(content).hexdigest() for name, content in files.items()
    }
    manifest: dict[str, Any] = {
        "result_bundle_version": RESULT_BUNDLE_VERSION,
        "evaluation_id": public_manifest.get("evaluation_id"),
        "evaluation_manifest_hash": public_manifest.get("manifest_hash"),
        "challenge_type": public_manifest.get("challenge_type"),
        "generator_version": public_manifest.get("generator_version"),
        "verifier_material_commitment": public_manifest.get("verifier_material_commitment"),
        "vica_version": __version__,
        "git_commit": git_commit(),
        "system_id": system_id,
        "created_at": datetime.now(UTC).isoformat(),
        "files": file_hashes,
    }
    manifest["bundle_hash"] = _bundle_hash(manifest)

    for name, content in files.items():
        (out_path / name).write_bytes(content)
    (out_path / "manifest.json").write_text(canonical_json_bytes(manifest).decode("utf-8"))

    return {
        "evaluation_id": manifest["evaluation_id"],
        "system_id": system_id,
        "challenge_count": len(results),
        "valid": sum(1 for r in results if r.valid),
        "no_submission": sum(1 for r in results if r.status == ReportStatus.NO_SUBMISSION),
        "bundle_hash": manifest["bundle_hash"],
        "out": str(out_path),
    }


def _jsonl_bytes(rows: list[Any]) -> bytes:
    return ("\n".join(canonical_json_bytes(r).decode("utf-8") for r in rows) + "\n").encode("utf-8")


def _bundle_hash(manifest: dict[str, Any]) -> str:
    without = {k: v for k, v in manifest.items() if k != "bundle_hash"}
    return stable_hash(without)


def load_result_bundle(result_bundle: str | Path) -> dict[str, Any]:
    """Load a Result Bundle and verify its integrity (bundle hash + per-file
    hashes). Returns the manifest.

    Safety: the manifest's ``files`` keys must be a fixed allowlist of bundle
    file names — path-traversal / absolute / nested / symlink entries are
    rejected before any file is opened, and each file is size-bounded.
    """
    root = Path(result_bundle).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise EvaluationFailure(f"{root} is not a Result Bundle (missing manifest.json)")
    if manifest_path.stat().st_size > MAX_RESULT_FILE_BYTES:
        raise EvaluationFailure("result bundle manifest is too large")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise EvaluationFailure("result bundle manifest is not a JSON object")
    if manifest.get("result_bundle_version") != RESULT_BUNDLE_VERSION:
        raise EvaluationFailure(
            f"unsupported result bundle version {manifest.get('result_bundle_version')!r}; "
            f"supported: {RESULT_BUNDLE_VERSION!r}"
        )
    if _bundle_hash(manifest) != manifest.get("bundle_hash"):
        raise EvaluationFailure("result bundle manifest hash mismatch (tampered or corrupted)")

    files = manifest.get("files") or {}
    if not isinstance(files, dict):
        raise EvaluationFailure("result bundle manifest 'files' is not an object")
    for name, expected in files.items():
        _check_result_file_name(name)
        if not isinstance(expected, str) or not expected.startswith("sha256:"):
            continue
        path = root / name
        _check_result_file(path, root)
        if not path.is_file():
            raise EvaluationFailure(f"result bundle missing file {name}")
        if path.is_symlink() or path.stat().st_size > MAX_RESULT_FILE_BYTES:
            raise EvaluationFailure(f"result bundle file {name} unsafe or too large")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected[len("sha256:"):]:
            raise EvaluationFailure(f"result bundle file {name} hash mismatch (modified)")
    _check_result_file(manifest_path, root)
    if manifest_path.is_symlink() or manifest_path.stat().st_size > MAX_RESULT_FILE_BYTES:
        raise EvaluationFailure("result bundle manifest unsafe or too large")
    return manifest


def _check_result_file_name(name: Any) -> None:
    if not isinstance(name, str) or name not in RESULT_FILE_ALLOWLIST:
        raise EvaluationFailure(f"unsafe result bundle file name {name!r}")


def _check_result_file(path: Path, root: Path) -> None:
    """Reject symlinks and any path that escapes the bundle root."""
    if path.is_symlink():
        raise EvaluationFailure(f"result bundle file {path.name} must not be a symlink")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise EvaluationFailure(f"result bundle file {path.name} escapes the bundle root")
    if not resolved.is_file():
        raise EvaluationFailure(f"result bundle missing file {path.name}")


__all__ = ["load_result_bundle", "verify_evaluation"]