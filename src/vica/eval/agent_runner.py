"""Coding Agent runner — v0.3 (docs/SPEC.md "Agent Mode").

``vica agent run`` is the natural interface for a Coding Agent: instead of
emitting a JSON candidate, the Agent is handed a **working directory** (the
materialized public REPO workspace) and edits files in place. VICA captures the
resulting ``git diff`` as the Patch Candidate and writes a Submission Bundle.

Flow per REPO challenge (§34):

    copy public workspace -> write task.md -> run Agent inside scratch (cwd)
        -> Agent edits files -> VICA captures patch -> write Submission
        -> delete scratch

Agent input (public only, §35): the workspace (buggy source + public tests +
``task.md``). It never sees the hidden tests, the reference patch, the verifier
secret, or anything under the private bundle.

Environment (§37): by default the Agent inherits only the sandbox safe
allowlist (locale/PATH). A user may explicitly forward a solver's own API keys
via ``--pass-env NAME``; VICA layers those on top of the allowlist. Reserved
verifier secrets (``VICA_VERIFIER_SECRET`` / ``VICA_PRIVATE_*``) are **always**
rejected, even if a user explicitly requests them.

Agent failures (§39) are recorded as distinct per-instance solver outcomes
(``timeout`` / ``nonzero_exit`` / ``no_patch`` / ``patch_too_large``), never
collapsed into a single status.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from vica.eval.bundle import load_public_bundle
from vica.eval.environment import execution_profile
from vica.eval.models import EvaluationFailure, ReportStatus
from vica.eval.submission import build_submission_bundle
from vica.repo.patch import MAX_PATCH_BYTES
from vica.repo.workspace import WorkspaceError, materialize_workspace
from vica.sandbox.runner import SandboxLimits, run_sandboxed

DEFAULT_TIMEOUT_S = 300.0
# Reserved verifier secrets that must never be forwarded to an Agent, even on
# explicit user request (docs/SPEC.md "Agent Environment").
FORBIDDEN_ENV_PREFIXES = ("VICA_VERIFIER_SECRET", "VICA_PRIVATE_")
# Generous output budget for an interactive/agentic command (streams logs).
MAX_AGENT_OUTPUT_BYTES = 4 << 20

# The REPO challenge type this runner drives. Only REPO-v0.1 workspaces are
# agent-addressable working directories in v0.3.
REPO_TYPE_NAME = "repo-v0.1"


def _agent_limits(timeout_s: float) -> SandboxLimits:
    """Sandbox envelope for an Agent command.

    Like the Command Solver, this is a bounded external-process runner, not a
    hardened sandbox: we keep the safe environment, process group, wall
    timeout, cwd, and bounded output, but impose no CPU/memory/FD rlimits that
    would break an ordinary interactive coding agent on a dev machine.
    """
    return SandboxLimits(
        cpu_seconds=0.0,
        wall_seconds=timeout_s,
        memory_bytes=0,
        max_processes=0,
        max_fds=0,
        max_output_bytes=MAX_AGENT_OUTPUT_BYTES,
        max_file_bytes=0,
    )


def _forwarded_environment(pass_env: list[str] | None) -> dict[str, str]:
    """Build the explicit env to forward from ``--pass-env`` names.

    Reads each requested name from the host environment. A requested name that
    is a reserved verifier secret (``VICA_VERIFIER_SECRET`` / ``VICA_PRIVATE_*``)
    is rejected with an :class:`EvaluationFailure` — we never forward it, even
    on explicit user request (§37). A name that is not set on the host is
    silently skipped (it would be empty anyway).
    """
    env: dict[str, str] = {}
    for name in pass_env or []:
        if not name or not isinstance(name, str):
            continue
        if name.startswith(FORBIDDEN_ENV_PREFIXES):
            raise EvaluationFailure(
                f"refusing to forward reserved verifier secret env {name!r} to an Agent"
            )
        value = _read_host_env(name)
        if value is not None:
            env[name] = value
    return env


def _read_host_env(name: str) -> str | None:
    import os

    return os.environ.get(name)


def run_agent(
    *,
    evaluation: str | Path,
    command: str,
    out: str | Path,
    system_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    pass_env: list[str] | None = None,
) -> dict[str, Any]:
    """Run *command* once per REPO challenge inside its workspace.

    Materializes each public workspace into a scratch directory, runs the Agent
    with cwd set to that workspace, captures the resulting patch, and writes a
    Submission Bundle. Returns a summary with per-challenge solver metadata.
    """
    if not command.strip():
        raise EvaluationFailure("agent command must not be empty")
    public_manifest, challenges = load_public_bundle(evaluation)
    evaluation_id = public_manifest.get("evaluation_id")
    if str(public_manifest.get("challenge_type")) != REPO_TYPE_NAME:
        raise EvaluationFailure(
            "vica agent run only drives the REPO workspace benchmark "
            f"(repo-v0.1); got challenge_type {public_manifest.get('challenge_type')!r}"
        )
    forwarded = _forwarded_environment(pass_env)

    rows: list[dict[str, Any]] = []
    per_challenge: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="vica-agent-") as root:
        scratch_root = Path(root)
        for ch in challenges:
            info = _run_one_agent(
                command, ch, scratch_root, timeout_s, forwarded
            )
            per_challenge.append(info)
            runner_meta: dict[str, Any] = {
                "solver_status": info["solver_status"].value if info["solver_status"] else None,
                "wall_time_ms": info["wall_time_ms"],
                "exit_code": info["exit_code"],
                "stdout_bytes": info["stdout_bytes"],
                "stderr_bytes": info["stderr_bytes"],
            }
            rows.append(
                {
                    "challenge_id": ch["id"],
                    "candidate": info["candidate"],
                    "metadata": {
                        "agent_command": command,
                        # Solver-supplied metadata is an untrusted self-report,
                        # kept under its own key and never in ``_vica_*``.
                        "solver_metadata": info.get("solver_metadata") or {},
                        "_vica_runner": runner_meta,
                    },
                }
            )

    result = build_submission_bundle(
        evaluation=evaluation,
        system_id=system_id,
        rows=rows,
        out=out,
        # The Execution Profile records the agent command identity, timeout, and
        # the forwarded env *names* (never values) for reproducibility (§63).
        system_metadata={
            "execution_profile": execution_profile(
                backend="local",
                timeout_s=timeout_s,
                network_policy="default",
                passed_env_names=list(forwarded.keys()),
                agent_command=command,
            )
        },
        # VICA-owned execution path: the wall time / exit code / solver outcome
        # below are genuinely measured by VICA, so the runner telemetry it
        # writes is trusted provenance.
        trusted_runner_telemetry=True,
    )
    result["evaluation_id"] = evaluation_id
    result["solved"] = len([p for p in per_challenge if p["candidate"] is not None])
    result["failures"] = [
        {
            k: p[k]
            for k in ("challenge_id", "exit_ok", "exit_code", "error", "solver_status")
        }
        for p in per_challenge
        if not p["exit_ok"] or p["candidate"] is None
    ]
    result["per_challenge"] = per_challenge
    return result


def _run_one_agent(
    command: str,
    ch: dict[str, Any],
    scratch_root: Path,
    timeout_s: float,
    forwarded_env: dict[str, str],
) -> dict[str, Any]:
    """Run the Agent once inside one materialized workspace.

    Returns an info dict with a ``candidate`` (the captured patch) when the
    Agent produced a well-formed, non-empty, size-bounded patch; otherwise a
    classified ``solver_status`` (timeout / nonzero_exit / no_patch /
    patch_too_large).
    """
    expected_id = str(ch.get("id"))
    info: dict[str, Any] = {
        "challenge_id": expected_id,
        "exit_ok": False,
        "exit_code": None,
        "wall_time_ms": 0.0,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "candidate": None,
        "error": None,
        "solver_status": None,
        "solver_metadata": None,
    }

    payload = ch.get("payload")
    if not isinstance(payload, dict):
        info["error"] = "internal_error"
        info["solver_status"] = ReportStatus.INTERNAL_ERROR
        return info
    manifest = payload.get("workspace_manifest")
    files = payload.get("workspace_files")
    if not isinstance(manifest, list) or not isinstance(files, dict):
        info["error"] = "internal_error"
        info["solver_status"] = ReportStatus.INTERNAL_ERROR
        return info

    ws = scratch_root / expected_id
    try:
        materialize_workspace(
            manifest,
            {k: _to_bytes(v) for k, v in files.items()},
            ws,
        )
    except (WorkspaceError, OSError) as exc:
        info["error"] = f"workspace materialization failed: {exc}"
        info["solver_status"] = ReportStatus.INTERNAL_ERROR
        return info

    # Baseline the workspace so we can capture the Agent's edits as a diff.
    baseline = _git_baseline(ws)
    if baseline is None:
        info["error"] = "cannot baseline workspace (git init/commit failed)"
        info["solver_status"] = ReportStatus.INTERNAL_ERROR
        return info

    start = time.perf_counter()
    result = run_sandboxed(
        ["/bin/sh", "-c", command],
        cwd=str(ws),
        env=forwarded_env,
        limits=_agent_limits(timeout_s),
    )
    info["wall_time_ms"] = (time.perf_counter() - start) * 1000.0
    info["exit_code"] = result.returncode
    info["stdout_bytes"] = len(result.stdout.encode("utf-8"))
    info["stderr_bytes"] = len(result.stderr.encode("utf-8"))

    if result.timed_out:
        info["error"] = "timeout"
        info["solver_status"] = ReportStatus.TIMEOUT
        return info
    if result.metadata.get("output_overflow"):
        info["error"] = "output_too_large"
        info["solver_status"] = ReportStatus.SANDBOX_ERROR
        return info
    if result.error_code is not None:
        info["error"] = "sandbox_error"
        info["solver_status"] = ReportStatus.SANDBOX_ERROR
        return info
    if result.returncode != 0:
        info["error"] = "nonzero_exit"
        info["solver_status"] = ReportStatus.NO_CANDIDATE
        return info

    patch, patch_error = _capture_patch(ws, baseline)
    if patch_error is not None or patch is None:
        info["error"] = patch_error or "no_patch"
        info["solver_status"] = (
            ReportStatus.NO_CANDIDATE
            if patch_error == "no_patch" or patch_error == "patch_too_large"
            else ReportStatus.INTERNAL_ERROR
        )
        return info

    info["exit_ok"] = True
    info["candidate"] = {"patch": patch}
    return info


def _git_baseline(ws: Path) -> str | None:
    """git init + baseline commit; return the baseline commit SHA or None."""
    try:
        subprocess.run(["git", "init", "-q", str(ws)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(ws), "add", "-A"], check=True, capture_output=True
        )
        subprocess.run(
            [
                "git", "-C", str(ws),
                "-c", "user.email=vica-agent@invalid",
                "-c", "user.name=vica-agent",
                "commit", "-q", "-m", "base",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        rev = subprocess.run(
            ["git", "-C", str(ws), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return rev.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _capture_patch(ws: Path, baseline: str) -> tuple[str | None, str | None]:
    """Return ``(patch, error)`` describing the Agent's edits vs baseline.

    ``git add -A`` stages new/deleted/modified files (including files the Agent
    created but did not stage), then ``git diff <baseline>`` captures everything
    relative to the baseline — robust even if the Agent committed its own work.
    """
    try:
        subprocess.run(
            ["git", "-C", str(ws), "add", "-A"], check=True, capture_output=True
        )
        diff = subprocess.run(
            ["git", "-C", str(ws), "diff", baseline],
            check=True,
            capture_output=True,
            text=True,
        )
        patch = diff.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None, "capture_failure"
    if not patch.strip():
        return None, "no_patch"
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        return None, "patch_too_large"
    return patch, None


def _to_bytes(v: Any) -> bytes:
    if isinstance(v, bytes):
        return v
    return str(v).encode("utf-8")


# ------------------------------------------------------------------ baselines


def run_noop(
    *,
    evaluation: str | Path,
    out: str | Path,
    system_id: str,
) -> dict[str, Any]:
    """NoOp baseline (§40): submit an empty patch for every REPO challenge.

    A NoOp patch changes nothing; it must pass the public tests (the honest
    hint) and fail the hidden tests (the discriminating negative control). Used
    to prove a released task is not vacuously passable.
    """
    public_manifest, challenges = load_public_bundle(evaluation)
    if str(public_manifest.get("challenge_type")) != REPO_TYPE_NAME:
        raise EvaluationFailure(
            "NoOp baseline only applies to the REPO workspace benchmark (repo-v0.1)"
        )
    rows = [
        {
            "challenge_id": ch["id"],
            "candidate": {"patch": ""},
            "metadata": {"baseline": "noop"},
        }
        for ch in challenges
    ]
    result = build_submission_bundle(
        evaluation=evaluation,
        system_id=system_id,
        rows=rows,
        out=out,
        trusted_runner_telemetry=True,
    )
    result["evaluation_id"] = public_manifest.get("evaluation_id")
    result["baseline"] = "noop"
    return result


def run_reference(
    *,
    evaluation: str | Path,
    out: str | Path,
    system_id: str,
    verifier_secret: str,
) -> dict[str, Any]:
    """Reference baseline (§41): submit the authoritative reference patch.

    The reference patch is derived from the verifier secret at generation time
    and is never placed in the solver-visible workspace. This is an
    evaluator/calibration tool that must pass 100% of the hidden tests; it is
    never shipped to a solver.
    """
    if not verifier_secret:
        raise EvaluationFailure("Reference baseline requires the verifier secret")
    public_manifest, challenges = load_public_bundle(evaluation)
    if str(public_manifest.get("challenge_type")) != REPO_TYPE_NAME:
        raise EvaluationFailure(
            "Reference baseline only applies to the REPO workspace benchmark (repo-v0.1)"
        )
    from vica.repo.generator import generate_with_solution

    rows: list[dict[str, Any]] = []
    for ch in challenges:
        _, solution = generate_with_solution(
            str(ch.get("seed", "")), int(ch.get("difficulty", 0)), verifier_secret
        )
        rows.append(
            {
                "challenge_id": ch["id"],
                "candidate": {"patch": solution["reference_patch"]},
                "metadata": {"baseline": "reference"},
            }
        )
    result = build_submission_bundle(
        evaluation=evaluation,
        system_id=system_id,
        rows=rows,
        out=out,
        trusted_runner_telemetry=True,
    )
    result["evaluation_id"] = public_manifest.get("evaluation_id")
    result["baseline"] = "reference"
    return result


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "FORBIDDEN_ENV_PREFIXES",
    "run_agent",
    "run_noop",
    "run_reference",
]