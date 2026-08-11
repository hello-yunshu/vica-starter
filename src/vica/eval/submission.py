"""Submission Bundle — M3 (docs/protocol/BUNDLE.md).

A Submission Bundle is the untrusted output of an external solver / coding
agent. It is file-exchange friendly: the agent only edits ``submissions.jsonl``
and needs no VICA Python API.

    submissions/
    ├── manifest.json         # evaluation_id, system_id, created_at, ...
    └── submissions.jsonl     # one {"challenge_id","candidate","metadata"} per line

Validation semantics (docs/BENCHMARK_METHODOLOGY.md "Submission validation"):
- unknown challenge id   -> reject the bundle (structured error)
- duplicate challenge id -> reject the ambiguous input (never silently pick
  the last one)
- missing challenge      -> recorded as NO_SUBMISSION (never confused with
  INVALID_SOLUTION)
- malformed candidate    -> recorded as a per-instance failure (PARSE_ERROR),
  not a whole-bundle rejection (candidate error isolation).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vica.eval.bundle import load_public_challenges, load_public_manifest
from vica.eval.models import SUBMISSION_BUNDLE_VERSION, EvaluationFailure

MAX_SUBMISSION_LINE_BYTES = 1 << 20
MAX_SUBMISSIONS = 100_000
# Reserved metadata namespace. ``_vica_*`` keys are owned by VICA and must
# never be accepted from an untrusted Submission Bundle (docs/protocol/BUNDLE.md
# "Solver self-report vs runner telemetry").
RESERVED_METADATA_PREFIX = "_vica_"
MAX_MANIFEST_BYTES = 1 << 20


def _strip_reserved(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop reserved ``_vica_*`` keys from untrusted solver metadata."""
    return {
        k: v for k, v in metadata.items() if not k.startswith(RESERVED_METADATA_PREFIX)
    }


def build_submission_bundle(
    *,
    evaluation: str | Path,
    system_id: str,
    rows: list[dict[str, Any]],
    out: str | Path,
    system_metadata: dict[str, Any] | None = None,
    trusted_runner_telemetry: bool = False,
) -> dict[str, Any]:
    """Create a Submission Bundle from raw solver rows.

    ``rows`` is a list of ``{"challenge_id", "candidate", "metadata"}``.
    Unknown / duplicate challenge ids are rejected (the bundle is invalid);
    missing challenges are recorded as NO_SUBMISSION at verify time.

    ``trusted_runner_telemetry`` must be ``True`` only when the caller is a
    VICA-owned execution path (the Command Solver) that genuinely measured the
    ``_vica_*`` telemetry it is writing. For any external solver rows it must
    stay ``False`` (default), in which case reserved ``_vica_*`` metadata keys
    are stripped so an untrusted solver cannot forge runner provenance.
    """
    expected = load_public_challenges(evaluation)
    expected_ids = {ch["id"] for ch in expected}
    evaluation_id = load_public_manifest(evaluation).get("evaluation_id")

    manifest: dict[str, Any] = {
        "submission_bundle_version": SUBMISSION_BUNDLE_VERSION,
        "evaluation_id": evaluation_id,
        "system_id": system_id,
        "system_metadata": dict(system_metadata or {}),
        "created_at": datetime.now(UTC).isoformat(),
    }

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationFailure("submission row must be an object")
        cid = row.get("challenge_id")
        if not isinstance(cid, str) or not cid:
            raise EvaluationFailure(f"submission missing challenge_id: {row!r}")
        if cid not in expected_ids:
            raise EvaluationFailure(
                f"unknown challenge id {cid!r} in submission (not part of this evaluation)"
            )
        if cid in seen:
            raise EvaluationFailure(f"duplicate challenge id {cid!r} in submission")
        seen.add(cid)
        candidate = row.get("candidate")
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if not trusted_runner_telemetry:
            metadata = _strip_reserved(metadata)
        normalized.append(
            {
                "challenge_id": cid,
                "candidate": candidate,
                "metadata": metadata,
            }
        )

    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)
    _write_json(out_path / "manifest.json", manifest)
    _write_jsonl(out_path / "submissions.jsonl", normalized)
    return {
        "evaluation_id": manifest["evaluation_id"],
        "system_id": system_id,
        "submitted": len(normalized),
        "expected": len(expected_ids),
        "out": str(out_path),
    }


def load_submission_bundle(
    submission: str | Path,
    evaluation: str | Path,
    trusted_runner_telemetry: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and validate a Submission Bundle against an evaluation.

    Returns ``(manifest, rows)``. Unknown challenge ids or duplicate ids raise
    ``EvaluationFailure`` (reject bundle). Missing challenges are *not* an
    error here — they become NO_SUBMISSION per-instance at verification.

    ``trusted_runner_telemetry`` is ``False`` for the file-exchange read path
    (default): reserved ``_vica_*`` metadata keys are stripped so a solver
    cannot forge VICA runner provenance. Only a VICA-owned execution path may
    opt in.
    """
    root = Path(submission).resolve()
    manifest_path = root / "manifest.json"
    lines_path = root / "submissions.jsonl"
    if not manifest_path.is_file() or not lines_path.is_file():
        raise EvaluationFailure(f"{root} is not a Submission Bundle (missing manifest/submissions)")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvaluationFailure("submission manifest must be a regular file")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise EvaluationFailure("submission manifest is too large")

    manifest = _read_json(manifest_path)
    if manifest.get("submission_bundle_version") != SUBMISSION_BUNDLE_VERSION:
        raise EvaluationFailure(
            f"unsupported submission bundle version "
            f"{manifest.get('submission_bundle_version')!r}; supported: "
            f"{SUBMISSION_BUNDLE_VERSION!r}"
        )
    expected = load_public_challenges(evaluation)
    expected_ids = {ch["id"] for ch in expected}
    evaluation_id = load_public_manifest(evaluation).get("evaluation_id")
    if manifest.get("evaluation_id") != evaluation_id:
        raise EvaluationFailure(
            "submission evaluation_id does not match the evaluation bundle"
        )

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    with lines_path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if line_no > MAX_SUBMISSIONS:
                raise EvaluationFailure(
                    f"submission exceeds MAX_SUBMISSIONS={MAX_SUBMISSIONS}"
                )
            if len(line.encode("utf-8")) > MAX_SUBMISSION_LINE_BYTES:
                raise EvaluationFailure(f"submission line {line_no} too large")
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise EvaluationFailure(
                    f"invalid JSON on submission line {line_no}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise EvaluationFailure(f"submission line {line_no} is not an object")
            cid = row.get("challenge_id")
            if not isinstance(cid, str) or not cid:
                raise EvaluationFailure(f"submission line {line_no} missing challenge_id")
            if cid not in expected_ids:
                raise EvaluationFailure(f"unknown challenge id {cid!r} in submission")
            if cid in seen:
                raise EvaluationFailure(f"duplicate challenge id {cid!r} in submission")
            seen.add(cid)
            if not trusted_runner_telemetry and isinstance(row.get("metadata"), dict):
                row = {**row, "metadata": _strip_reserved(row["metadata"])}
            rows.append(row)
    return manifest, rows


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise EvaluationFailure(f"cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvaluationFailure(f"{path} is not a JSON object")
    return data


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    from vica.protocol.serialization import canonical_json_bytes

    path.write_text(canonical_json_bytes(obj).decode("utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    from vica.protocol.serialization import canonical_json_bytes

    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(canonical_json_bytes(row).decode("utf-8") + "\n")


__all__ = ["build_submission_bundle", "load_submission_bundle"]