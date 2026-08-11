"""External Command Solver — Mode B (docs/protocol/BUNDLE.md).

``vica solver run --command ...`` runs a single external command once per
public challenge: the solver reads the challenge JSON via stdin and writes an
answer JSON via stdout. This is the second-priority solver mode; File Exchange
(Mode A) is the first and is always preferred for Coding Agents.

Protocol (v0.2, deliberately minimal — no RPC):

    stdin  <- {"protocol_version": "0.2", "challenge": {id,type,generator_version,
                                                       seed,difficulty,
                                                       verifier_material_commitment,
                                                       payload}}
    stdout -> {"challenge_id": "...", "candidate": ..., "metadata": {...}}

Security & provenance guarantees:

- The child runs under the sandbox's safe child environment (an allowlist, not
  ``os.environ``), so evaluator secrets (``VICA_VERIFIER_SECRET``, API keys,
  tokens) are **never** inherited by the external solver.
- The child runs in its own process group with a real wall-clock timeout and a
  bounded streaming output read (SIGKILL on timeout / overflow), so a runaway
  solver cannot exhaust host memory or leak a detached process.
- The returned ``challenge_id`` is validated against the one we sent: a
  mismatched id is a protocol failure (``parse_error``), never silently
  accepted as a valid candidate for a different challenge.
- Solver failures (timeout / parse_error / nonzero_exit / output overflow /
  empty output) are recorded as **per-instance solver outcomes** in the
  Submission Bundle (``metadata._vica_runner.solver_status``). They are never
  collapsed into ``NO_SUBMISSION`` (which means "no row was submitted at all")
  and never reported as ``INVALID_SOLUTION`` (a wrong answer).

The runner measures wall time; that latency is trusted runner telemetry and is
carried into ``ResultRecord.solve_wall_time_ms`` at verify time.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from vica.eval.bundle import load_public_bundle
from vica.eval.models import EvaluationFailure, ReportStatus
from vica.eval.submission import build_submission_bundle
from vica.sandbox.runner import SandboxLimits, run_sandboxed

PROTOCOL_VERSION = "0.2"
DEFAULT_TIMEOUT_S = 120.0
MAX_CANDIDATE_BYTES = 1 << 20

# The command solver is a *bounded external process runner*, not a hardened
# sandbox. We keep the sandbox's safe environment, process group, wall timeout
# and bounded output, but do not impose CPU/memory/FD/file rlimits that would
# break an ordinary user-provided command on a normal dev machine (macOS).
def _solver_limits(timeout_s: float) -> SandboxLimits:
    return SandboxLimits(
        cpu_seconds=0.0,
        wall_seconds=timeout_s,
        memory_bytes=0,
        max_processes=0,
        max_fds=0,
        max_output_bytes=MAX_CANDIDATE_BYTES,
        max_file_bytes=0,
    )


def solve_with_command(
    *,
    evaluation: str | Path,
    command: str,
    out: str | Path,
    system_id: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run *command* once per public challenge and produce a Submission Bundle.

    Returns a summary including per-challenge solve metadata (wall time, exit
    code, stdout/stderr size). Every challenge gets a row in the Submission
    Bundle — a solver failure is recorded as a per-instance solver outcome
    (``metadata._vica_runner.solver_status``), never as a missing submission.
    """
    if not command.strip():
        raise EvaluationFailure("command must not be empty")
    public_manifest, challenges = load_public_bundle(evaluation)
    evaluation_id = public_manifest.get("evaluation_id")

    rows: list[dict[str, Any]] = []
    per_challenge: list[dict[str, Any]] = []
    for ch in challenges:
        info = _run_one(command, ch, timeout_s)
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
                    "solver_command": command,
                    # Solver-supplied metadata is an untrusted self-report. It is
                    # preserved for provenance but kept under its own key so it can
                    # never collide with the VICA-owned ``_vica_*`` telemetry below.
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
        # This is a VICA-owned execution path: the wall time, exit code, and
        # solver outcome below are genuinely measured by VICA, so the runner
        # telemetry it writes is trusted provenance (unlike a file-exchange
        # Submission which may not claim ``_vica_*`` keys).
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


def _run_one(command: str, ch: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    expected_id = str(ch.get("id"))
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "challenge": {
            "id": expected_id,
            "type": ch.get("type"),
            "generator_version": ch.get("generator_version"),
            "seed": ch.get("seed"),
            "difficulty": ch.get("difficulty"),
            "verifier_material_commitment": ch.get("verifier_material_commitment"),
            "payload": ch.get("payload"),
        },
    }
    input_text = json.dumps(payload)

    start = time.perf_counter()
    result = run_sandboxed(
        ["/bin/sh", "-c", command],
        stdin=input_text,
        limits=_solver_limits(timeout_s),
    )
    wall_ms = (time.perf_counter() - start) * 1000.0

    info: dict[str, Any] = {
        "challenge_id": expected_id,
        "exit_ok": False,
        "exit_code": result.returncode,
        "wall_time_ms": wall_ms,
        "stdout_bytes": len(result.stdout.encode("utf-8")),
        "stderr_bytes": len(result.stderr.encode("utf-8")),
        "candidate": None,
        "error": None,
        "solver_status": None,
    }

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

    obj, parse_error = _parse_candidate(result.stdout, expected_id)
    if parse_error is not None or obj is None:
        info["error"] = parse_error or "no_candidate"
        # Empty output is a "no candidate" solver outcome, not a malformed
        # protocol response (docs/BENCHMARK_METHODOLOGY.md "Failure taxonomy").
        info["solver_status"] = (
            ReportStatus.NO_CANDIDATE
            if info["error"] == "no_candidate"
            else ReportStatus.PARSE_ERROR
        )
        return info

    info["exit_ok"] = True
    info["candidate"] = obj["candidate"]
    # Preserve the solver's self-reported metadata (untrusted) for provenance.
    solver_meta = obj.get("metadata")
    info["solver_metadata"] = solver_meta if isinstance(solver_meta, dict) else {}
    return info


def _parse_candidate(stdout: str, expected_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the solver's stdout as a protocol response.

    Returns ``(obj, None)`` on a well-formed response whose ``challenge_id``
    matches *expected_id*, else ``(None, error)`` where *error* classifies the
    failure (``no_candidate`` for empty output, ``parse_error`` for malformed
    JSON or a mismatched ``challenge_id``).
    """
    text = stdout.strip()
    if not text:
        return None, "no_candidate"
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None, "parse_error"
    if not isinstance(obj, dict) or "candidate" not in obj:
        return None, "parse_error"
    if str(obj.get("challenge_id")) != expected_id:
        return None, "wrong_challenge_id"
    return obj, None


__all__ = ["DEFAULT_TIMEOUT_S", "PROTOCOL_VERSION", "solve_with_command"]