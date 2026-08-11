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

The runner measures wall time, exit code, and stdout/stderr sizes. Candidate
JSON that fails to parse is recorded as a per-instance failure so one bad
line never discards the whole batch. timeout / nonzero exit / oversized output
are normal solver outcomes, not evaluation failures.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from vica.eval.bundle import load_public_challenges, load_public_manifest
from vica.eval.models import EvaluationFailure
from vica.eval.submission import build_submission_bundle

PROTOCOL_VERSION = "0.2"
DEFAULT_TIMEOUT_S = 120.0
MAX_CANDIDATE_BYTES = 1 << 20


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
    code, stdout/stderr size). Solver failures are captured per instance; the
    Submission Bundle is still produced so verification can classify them.
    """
    if not command.strip():
        raise EvaluationFailure("command must not be empty")
    challenges = load_public_challenges(evaluation)
    evaluation_id = load_public_manifest(evaluation).get("evaluation_id")

    rows: list[dict[str, Any]] = []
    per_challenge: list[dict[str, Any]] = []
    for ch in challenges:
        info = _run_one(command, ch, timeout_s)
        per_challenge.append(info)
        if info["exit_ok"] and info["candidate"] is not None:
            rows.append(
                {
                    "challenge_id": ch["id"],
                    "candidate": info["candidate"],
                    "metadata": {
                        "solver_command": command,
                        "wall_time_ms": info["wall_time_ms"],
                        "exit_code": info["exit_code"],
                        "stdout_bytes": info["stdout_bytes"],
                        "stderr_bytes": info["stderr_bytes"],
                    },
                }
            )
        else:
            # No usable candidate for this challenge: leave it out so verify
            # records NO_SUBMISSION (never confuse with INVALID_SOLUTION).
            pass

    result = build_submission_bundle(
        evaluation=evaluation, system_id=system_id, rows=rows, out=out
    )
    result["evaluation_id"] = evaluation_id
    result["solved"] = len([p for p in per_challenge if p["candidate"] is not None])
    result["failures"] = [
        {k: p[k] for k in ("challenge_id", "exit_ok", "exit_code", "error")}
        for p in per_challenge
        if not p["exit_ok"] or p["candidate"] is None
    ]
    result["per_challenge"] = per_challenge
    return result


def _run_one(command: str, ch: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "challenge": {
            "id": ch.get("id"),
            "type": ch.get("type"),
            "generator_version": ch.get("generator_version"),
            "seed": ch.get("seed"),
            "difficulty": ch.get("difficulty"),
            "verifier_material_commitment": ch.get("verifier_material_commitment"),
            "payload": ch.get("payload"),
        },
    }
    input_bytes = json.dumps(payload).encode("utf-8")
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            input=input_bytes,
            capture_output=True,
            timeout=timeout_s,
            shell=True,
        )
        wall_ms = (time.perf_counter() - start) * 1000.0
    except subprocess.TimeoutExpired:
        return {
            "challenge_id": ch.get("id"),
            "exit_ok": False,
            "exit_code": None,
            "wall_time_ms": (time.perf_counter() - start) * 1000.0,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "candidate": None,
            "error": "timeout",
        }
    except OSError as exc:  # pragma: no cover - shell spawn failure
        return {
            "challenge_id": ch.get("id"),
            "exit_ok": False,
            "exit_code": None,
            "wall_time_ms": (time.perf_counter() - start) * 1000.0,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "candidate": None,
            "error": f"spawn_error: {exc}",
        }

    stdout = proc.stdout
    if len(stdout) > MAX_CANDIDATE_BYTES:
        return {
            "challenge_id": ch.get("id"),
            "exit_ok": False,
            "exit_code": proc.returncode,
            "wall_time_ms": wall_ms,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(proc.stderr),
            "candidate": None,
            "error": "output_too_large",
        }
    if proc.returncode != 0:
        return {
            "challenge_id": ch.get("id"),
            "exit_ok": False,
            "exit_code": proc.returncode,
            "wall_time_ms": wall_ms,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(proc.stderr),
            "candidate": None,
            "error": "nonzero_exit",
        }

    parsed = _parse_candidate(stdout)
    return {
        "challenge_id": ch.get("id"),
        "exit_ok": parsed is not None,
        "exit_code": proc.returncode,
        "wall_time_ms": wall_ms,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(proc.stderr),
        "candidate": parsed.get("candidate") if isinstance(parsed, dict) else None,
        "error": None if parsed is not None else "parse_error",
    }


def _parse_candidate(stdout: bytes) -> dict[str, Any] | None:
    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "candidate" not in obj:
        return None
    return obj


__all__ = ["DEFAULT_TIMEOUT_S", "PROTOCOL_VERSION", "solve_with_command"]