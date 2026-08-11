"""Independent reverification — M4 (docs/BENCHMARK_METHODOLOGY.md).

``vica reverify`` does **not** re-invoke a solver. It loads a stored Result
Bundle, reloads the raw candidates and public challenges, loads the evaluator
verifier material (from the private evaluation bundle), and runs the same
authoritative ``verify_submission`` again, then recomputes metrics.

Strict mode (the only mode in v0.2) refuses to reverify when the stored
generator version, material commitment, challenge ids, or verifier semantics
do not match the evaluation being used — so a third party must hold the
correct evaluator material to reproduce identical valid / score / error
semantics.

Telemetry (``solve_wall_time_ms`` / ``verify_time_us``) is not required to be
identical between the original run and the reverification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vica.eval.bundle import load_public_manifest, load_verifier_material
from vica.eval.metrics import summarize
from vica.eval.models import EvaluationFailure, ReportStatus, ResultRecord, to_result_record
from vica.eval.verify import load_result_bundle
from vica.protocol.models import CandidateSubmission, Challenge
from vica.verifier.verifier import verify_submission

# The Result Bundle stores its own copy of the challenges and raw submissions,
# so reverification is self-contained given the evaluator verifier material.
_CHALLENGES = "challenges.jsonl"
_SUBMISSIONS = "submissions.jsonl"
_RESULTS = "results.jsonl"


def reverify_bundle(
    result_bundle: str | Path,
    evaluation: str | Path,
    system_id: str | None = None,
) -> dict[str, Any]:
    """Strictly reverify a Result Bundle against an evaluation.

    Loads the stored challenges + raw candidates, reloads the evaluator
    verifier material, re-runs ``verify_submission``, and compares the
    recomputed (valid, score, error_code) against the stored results.
    Returns a dict with per-challenge matches and recomputed metrics.
    """
    manifest = load_result_bundle(result_bundle)
    root = Path(result_bundle).resolve()

    evaluation_id = manifest.get("evaluation_id")
    pub = load_public_manifest(evaluation)
    if pub.get("evaluation_id") != evaluation_id:
        raise EvaluationFailure(
            "result bundle evaluation_id does not match the evaluation bundle"
        )

    # Strict mode: the evaluation used for reverify must carry the same
    # generator version and material commitment as the result bundle.
    stored_gen = manifest.get("generator_version")
    # The result manifest does not store the commitment directly; read it from
    # the stored evaluation copy inside the bundle.
    stored_eval = _read_json(root / "evaluation.json")
    stored_commit = _norm(stored_eval.get("verifier_material_commitment"))
    if pub.get("generator_version") != stored_gen:
        raise EvaluationFailure(
            f"strict reverify refused: evaluation generator {pub.get('generator_version')!r} "
            f"!= result bundle {stored_gen!r}"
        )
    if _norm(pub.get("verifier_material_commitment")) != stored_commit:
        raise EvaluationFailure(
            "strict reverify refused: verifier material commitment mismatch between "
            "evaluation and result bundle"
        )

    material = load_verifier_material(evaluation)
    verifier_secret = material.get("verifier_secret") or None
    if manifest.get("evaluation_id") and pub.get("verifier_material_commitment") is not None:
        if not verifier_secret:
            raise EvaluationFailure(
                "secret-bound evaluation has no verifier secret in the private material"
            )

    if system_id is None:
        _system = manifest.get("system_id")
        if not isinstance(_system, str) or not _system:
            raise EvaluationFailure("result bundle has no system_id; pass --system")
        system_id = _system

    challenges = _read_jsonl(root / _CHALLENGES)
    submissions = _read_jsonl(root / _SUBMISSIONS)
    stored_results = _read_jsonl(root / _RESULTS)

    submissions_by_id = {s["challenge_id"]: s for s in submissions}
    stored_by_id = {r["challenge_id"]: r for r in stored_results}

    recomputed: list[ResultRecord] = []
    mismatches: list[dict[str, Any]] = []
    for ch in challenges:
        cid = ch["id"]
        stored = stored_by_id.get(cid)
        row = submissions_by_id.get(cid)
        if stored is None:
            raise EvaluationFailure(f"result bundle missing stored result for {cid}")
        if row is None:
            # Original was NO_SUBMISSION; recompute the same.
            record = to_result_record(
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
        else:
            record = _reverify_one(
                ch, row.get("candidate"), row.get("metadata") or {}, system_id, verifier_secret
            )
        mismatch = _compare(stored, record)
        if mismatch:
            mismatches.append(mismatch)
        recomputed.append(record)

    metrics = summarize(recomputed)
    return {
        "evaluation_id": evaluation_id,
        "system_id": system_id,
        "challenge_count": len(challenges),
        "matched": len(challenges) - len(mismatches),
        "mismatches": mismatches,
        "ok": not mismatches,
        "metrics": metrics,
    }


def _reverify_one(
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


def _compare(stored: dict[str, Any], recomputed: ResultRecord) -> dict[str, Any] | None:
    """Compare the recomputed result against the stored one.

    Only the deterministic semantics (valid / score / error_code) must match;
    solve_wall_time_ms / verify_time_us are telemetry and may differ.
    """
    stored_code = stored.get("error_code")
    recomputed_code = recomputed.error_code.value if recomputed.error_code else None
    if (
        stored.get("valid") == recomputed.valid
        and _norm_score(stored.get("score")) == _norm_score(recomputed.score)
        and stored_code == recomputed_code
    ):
        return None
    return {
        "challenge_id": recomputed.challenge_id,
        "stored_valid": stored.get("valid"),
        "recomputed_valid": recomputed.valid,
        "stored_score": stored.get("score"),
        "recomputed_score": recomputed.score,
        "stored_error_code": stored_code,
        "recomputed_error_code": recomputed_code,
    }


def _norm_score(v: Any) -> float:
    try:
        return round(float(v), 9)
    except (TypeError, ValueError):
        return float("nan")


def _norm(v: Any) -> str | None:
    return str(v) if v is not None else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise EvaluationFailure(f"cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvaluationFailure(f"{path} is not a JSON object")
    return data


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvaluationFailure(f"missing file {path}")
    result: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
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


__all__ = ["reverify_bundle"]