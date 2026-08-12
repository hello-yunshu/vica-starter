"""Study orchestration — v0.4 (docs/REPRODUCIBILITY.md "Study").

A Study is a *multi-run benchmark* over the same Task Pack:

    for system in systems
        for replicate in range(replicates)
            run(system, task pack) -> submission -> verify -> result

It is deliberately a simple nested loop (§71) — no DAG, no job queue, no remote
worker. Each system is one of:

- an Agent command (``vica study run --command ...``), run once per REPO task;
- the NoOp baseline (empty patch, must fail hidden);
- the Reference baseline (authoritative patch, must pass — evaluator only);
- a pre-built Submission Bundle (``vica agent run`` output).

Replicates are part of the *run* identity, never the Challenge / Task Pack
identity (§69). A system's aggregated result reports pass probability, median
latency, cost coverage and failure distribution across replicates — never just
the best attempt (§75).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from vica.eval.agent_runner import run_agent, run_noop, run_reference
from vica.eval.bundle import load_public_manifest
from vica.eval.stats import success_rate_with_ci
from vica.eval.taskpack import derive_task_pack
from vica.eval.verify import verify_evaluation

SystemKind = Literal["agent", "noop", "reference", "submission"]


@dataclass
class StudySystem:
    """One system participating in a Study."""

    system_id: str
    kind: SystemKind
    # ``agent``: command + optional pass_env / timeout.
    command: str | None = None
    pass_env: list[str] | None = None
    timeout_s: float = 300.0
    # ``submission``: a pre-built Submission Bundle directory.
    submission: str | Path | None = None
    # ``reference``: evaluator/calibration only.
    verifier_secret: str | None = None
    # emit a distinct submission bundle per replicate
    replicate_submissions: bool = False


@dataclass
class ReplicateResult:
    """A single run of one system over the task pack."""

    system_id: str
    replicate: int
    result_bundle: str
    valid: int
    challenge_count: int
    no_submission: int
    metrics: dict[str, Any] = field(default_factory=dict)


def _run_system_once(
    spec: StudySystem,
    evaluation: str | Path,
    run_dir: Path,
    replicate: int,
    verifier_secret: str | None,
    study_root: Path,
) -> ReplicateResult:
    # Each replicate owns a persistent directory ``<study-out>/runs/<sid>/r<rep>``
    # containing the `submission/` and `result/` bundles. They are never deleted
    # after the study returns (docs §22-25).
    sub = run_dir / "submission"
    res = run_dir / "result"
    if spec.kind == "agent":
        assert spec.command
        run_agent(
            evaluation=evaluation,
            command=spec.command,
            out=sub,
            system_id=spec.system_id,
            timeout_s=spec.timeout_s,
            pass_env=spec.pass_env,
        )
    elif spec.kind == "noop":
        run_noop(evaluation=evaluation, out=sub, system_id=spec.system_id)
    elif spec.kind == "reference":
        run_reference(
            evaluation=evaluation,
            out=sub,
            system_id=spec.system_id,
            verifier_secret=spec.verifier_secret or verifier_secret or "",
        )
    elif spec.kind == "submission":
        return _verify_existing(spec, evaluation, res, study_root)
    else:  # pragma: no cover - exhaustive
        raise ValueError(f"unknown system kind {spec.kind!r}")

    summary = verify_evaluation(
        evaluation=evaluation,
        submission=sub,
        out=res,
        system_id=spec.system_id,
        trusted_runner_telemetry=True,
    )
    return ReplicateResult(
        system_id=spec.system_id,
        replicate=replicate,
        result_bundle=_portable_rel(study_root, res),
        valid=int(summary["valid"]),
        challenge_count=int(summary["challenge_count"]),
        no_submission=int(summary["no_submission"]),
        metrics=_load_metrics(res),
    )


def _portable_rel(root: Path, path: Path) -> str:
    """A POSIX-style path relative to the study root (portable, no /tmp leaks)."""
    return path.relative_to(root).as_posix()


def _verify_existing(
    spec: StudySystem, evaluation: str | Path, res: Path, study_root: Path
) -> ReplicateResult:
    assert spec.submission is not None
    summary = verify_evaluation(
        evaluation=evaluation,
        submission=spec.submission,
        out=res,
        system_id=spec.system_id,
        trusted_runner_telemetry=False,
    )
    return ReplicateResult(
        system_id=spec.system_id,
        replicate=0,
        result_bundle=_portable_rel(study_root, res),
        valid=int(summary["valid"]),
        challenge_count=int(summary["challenge_count"]),
        no_submission=int(summary["no_submission"]),
        metrics=_load_metrics(res),
    )


def _load_metrics(res: Path) -> dict[str, Any]:
    """Read the authoritative ``metrics.json`` written by a Result Bundle.

    The metrics carry per-difficulty correctness that the study re-aggregates
    across replicates; a missing/unreadable metrics file degrades to ``{}``
    (the study still reports challenge/valid counts from the verify summary).
    """
    try:
        payload = json.loads((res / "metrics.json").read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def run_study(
    *,
    evaluation: str | Path,
    systems: list[StudySystem],
    replicates: int = 1,
    out: str | Path,
    verifier_secret: str | None = None,
) -> dict[str, Any]:
    """Run a Study: every system x every replicate over the task pack.

    Returns an aggregate summary (no secrets) with per-system replicate results
    and layered metrics by difficulty / task_kind / template.
    """
    if replicates < 1:
        raise ValueError("replicates must be >= 1")
    public_manifest = load_public_manifest(evaluation)
    task_pack = derive_task_pack(public_manifest, _challenges(evaluation))

    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)

    all_runs: list[ReplicateResult] = []
    for spec in systems:
        reps = 1 if spec.kind == "submission" else replicates
        for rep in range(reps):
            # Persistent per-replicate directory (never deleted after the study
            # returns, §22-25). Result paths are recorded relative to the study
            # root so ``study.json`` stays portable (§24).
            run_dir = out_path / "runs" / _safe_component(spec.system_id) / f"r{rep}"
            run_dir.mkdir(parents=True, exist_ok=True)
            all_runs.append(
                _run_system_once(
                    spec, evaluation, run_dir, rep, verifier_secret, out_path
                )
            )

    systems_summary = _summarize_systems(all_runs)
    # Persist an aggregate study report in the output dir.
    (out_path / "study.json").write_text(
        _canonical(_study_document(task_pack, systems_summary))
    )
    return {
        "evaluation_id": public_manifest.get("evaluation_id"),
        "task_pack_id": task_pack.task_pack_id,
        "task_pack_hash": task_pack.task_pack_hash,
        "systems": {
            sid: _public_system_summary(sid, systems_summary[sid])
            for sid in sorted(systems_summary)
        },
        "out": str(out_path),
    }


def _challenges(evaluation: str | Path) -> list[dict[str, Any]]:
    from vica.eval.bundle import load_public_challenges

    return load_public_challenges(evaluation)


def _summarize_systems(
    runs: list[ReplicateResult],
) -> dict[str, dict[str, Any]]:
    by_system: dict[str, dict[str, Any]] = {}
    for run in runs:
        bucket = by_system.setdefault(
            run.system_id,
            {
                "replicates": [],
                "valid": 0,
                "challenge_count": 0,
                "latency_ms": [],
                "failure_counts": {},
                "by_difficulty": {},
                "by_task_kind": {},
                "by_template": {},
            },
        )
        bucket["replicates"].append(_public_replicate(run))
        bucket["valid"] += run.valid
        bucket["challenge_count"] += run.challenge_count
        _accumulate_metrics(bucket, run)
    # Aggregate per-system pass probability + CI across the task pack.
    for _sid, bucket in by_system.items():
        total = bucket["challenge_count"]
        valid = bucket["valid"]
        rate = success_rate_with_ci(valid, total) if total else {"success_rate": None}
        bucket["success_rate"] = rate.get("success_rate")
        bucket["ci_lower"] = rate.get("ci_lower")
        bucket["ci_upper"] = rate.get("ci_upper")
    return by_system


def _safe_component(name: str) -> str:
    """Validate a system_id into a single safe, unambiguous path component.

    The system_id is a benchmark provenance identity and is emitted into the
    on-disk run path, so we REJECT (never silently normalize) anything that is
    not a single ``[A-Za-z0-9._-]`` component. A lossy sanitizer would collapse
    distinct identities (e.g. ``ab`` and ``a/b``) onto the same path and could
    allow ``.`` / ``..``; instead we raise ``ValueError`` so a collision is
    impossible and traversal is impossible.
    """
    if not isinstance(name, str) or not _SYSTEM_ID_RE.match(name):
        raise ValueError(
            f"invalid system_id {name!r}: must match "
            r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ and be a single path component"
        )
    return name


_SYSTEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _accumulate_metrics(bucket: dict[str, Any], run: ReplicateResult) -> None:
    metrics = run.metrics
    if metrics:
        latency = metrics.get("latency") or {}
        if latency.get("mean") is not None:
            bucket["latency_ms"].append(float(latency["mean"]))
        taxonomy = metrics.get("failure_taxonomy") or {}
        for status, count in (taxonomy.get("counts") or {}).items():
            bucket["failure_counts"][status] = (
                bucket["failure_counts"].get(status, 0) + int(count)
            )
        for layer_key in ("by_difficulty", "by_task_kind", "by_template"):
            _accumulate_layer(bucket, metrics, layer_key)


def _accumulate_layer(
    bucket: dict[str, Any], metrics: dict[str, Any], key: str
) -> None:
    """Sum per-label valid/total counts from a metrics layer into the bucket."""
    target = bucket[key]
    for label, row in (metrics.get(key) or {}).items():
        cell = target.setdefault(label, {"valid": 0, "total": 0})
        cell["valid"] += int(row.get("valid", 0))
        cell["total"] += int(row.get("n", 0))


def _public_replicate(run: ReplicateResult) -> dict[str, Any]:
    return {
        "system_id": run.system_id,
        "replicate": run.replicate,
        "result_bundle": run.result_bundle,
        "valid": run.valid,
        "challenge_count": run.challenge_count,
        "no_submission": run.no_submission,
    }


def _public_system_summary(sid: str, bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "system_id": sid,
        "replicates": len(bucket["replicates"]),
        "valid": bucket["valid"],
        "challenge_count": bucket["challenge_count"],
        "success_rate": bucket["success_rate"],
        "ci_lower": bucket["ci_lower"],
        "ci_upper": bucket["ci_upper"],
        "median_latency_ms": _median(bucket["latency_ms"]),
        "failure_counts": bucket["failure_counts"],
        "by_difficulty": bucket["by_difficulty"],
        "by_task_kind": bucket["by_task_kind"],
        "by_template": bucket["by_template"],
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _study_document(task_pack: Any, systems: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_pack_id": task_pack.task_pack_id,
        "task_pack_version": task_pack.task_pack_version,
        "task_pack_hash": task_pack.task_pack_hash,
        "systems": {
            sid: {
                **_public_system_summary(sid, systems[sid]),
                # Full per-replicate provenance with portable result paths (§25).
                "replicates": list(systems[sid]["replicates"]),
            }
            for sid in sorted(systems)
        },
    }


def _canonical(obj: Any) -> str:
    from vica.protocol.serialization import canonical_json_bytes

    return canonical_json_bytes(obj).decode("utf-8") + "\n"


__all__ = [
    "ReplicateResult",
    "StudySystem",
    "run_study",
]