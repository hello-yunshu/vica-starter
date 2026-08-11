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

    _validate_bundle_pair(public_manifest, private_manifest, material)

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


def _verify_one(
    ch: dict[str, Any],
    candidate: Any,
    metadata: dict[str, Any],
    system_id: str,
    verifier_secret: str | None,
) -> ResultRecord:
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
        verify_time_us=result.verify_time_us,
        candidate=candidate,
        metadata=meta,
    )


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


def _validate_bundle_pair(
    public_manifest: dict[str, Any],
    private_manifest: dict[str, Any],
    material: dict[str, Any],
) -> None:
    """Cross-check public/private consistency before any verification.

    A wrong private bundle (e.g. evaluation A public paired with evaluation B
    private) is an evaluator configuration failure and must abort before any
    solver is judged.
    """
    if private_manifest.get("public_manifest_hash") != public_manifest.get("manifest_hash"):
        raise EvaluationFailure(
            "private bundle does not reference this public manifest (wrong private material)"
        )
    if private_manifest.get("challenges_hash") != public_manifest.get("challenges_hash"):
        raise EvaluationFailure("private/public challenges_hash mismatch")
    pub_commitment = public_manifest.get("verifier_material_commitment")
    priv_commitment = private_manifest.get("verifier_material_commitment")
    if _norm(pub_commitment) != _norm(priv_commitment):
        raise EvaluationFailure(
            "verifier material commitment mismatch between public and private bundle "
            "(wrong or missing verifier material)"
        )
    mat_commitment = material.get("verifier_material_commitment")
    if pub_commitment is not None and _norm(mat_commitment) != _norm(pub_commitment):
        raise EvaluationFailure(
            "verifier-material.json does not commit to the evaluation's material"
        )
    if pub_commitment is not None and not material.get("verifier_secret"):
        raise EvaluationFailure(
            "secret-bound evaluation has no verifier secret in the private material"
        )


def _norm(v: Any) -> str | None:
    return str(v) if v is not None else None


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
    hashes). Returns the manifest."""
    root = Path(result_bundle).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise EvaluationFailure(f"{root} is not a Result Bundle (missing manifest.json)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise EvaluationFailure("result bundle manifest is not a JSON object")
    if _bundle_hash(manifest) != manifest.get("bundle_hash"):
        raise EvaluationFailure("result bundle manifest hash mismatch (tampered or corrupted)")
    files = manifest.get("files") or {}
    for name, expected in files.items():
        if not isinstance(expected, str) or not expected.startswith("sha256:"):
            continue
        path = root / name
        if not path.is_file():
            raise EvaluationFailure(f"result bundle missing file {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected[len("sha256:"):]:
            raise EvaluationFailure(f"result bundle file {name} hash mismatch (modified)")
    return manifest


__all__ = ["load_result_bundle", "verify_evaluation"]