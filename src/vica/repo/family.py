"""REPO-v0.1 ChallengeFamily — deterministic verifier for patch candidates.

A REPO challenge presents a small Python workspace; the candidate is a git
unified-diff patch (see :mod:`vica.repo.patch`). The authoritative verifier
(docs/SPEC.md "REPO Verifier flow") runs the exact pipeline:

    validate workspace hash -> validate patch artifact -> materialize into a
    temp dir (never the original) -> apply the patch -> structural constraints
    -> public tests -> secret-derived hidden tests -> deterministic result.

Key invariants:

- **Never runs on the original workspace.** The workspace is materialized into
  a fresh temporary directory and discarded afterward (§23).
- **Public tests are the honest hint.** A NoOp patch passes them (the buggy
  source already agrees with the reference on public inputs).
- **Hidden tests are the discriminating negative control.** They are
  regenerated deterministically from the verifier secret at verification time
  (``generator.hidden_tests_for``), so they are never shipped to solvers and a
  NoOp patch fails them (§40).
- **Candidate execution is process-separated from the expected values.**
  The patched ``solution.py`` runs in an isolated subprocess that receives
  ONLY the case inputs (never the expected outputs, the hidden list, or the
  verifier secret). The subprocess returns the actual outputs; the parent
  compares actuals against expected. Candidate Python frames therefore cannot
  reach evaluator-owned expected values via frame inspection, and patching
  ``builtins`` / ``json`` in the candidate cannot affect the parent's
  comparison. This is a verifier correctness boundary, not a hardened
  OS-level sandbox claim.
- **Untrusted code runs in the sandbox.** The patched ``solution.py`` is loaded
  in a sandboxed subprocess (``vica.sandbox``) with resource limits, a minimal
  environment (no host secrets), a bounded output, and a clean cwd (§31). We
  call ``solve`` directly rather than pytest so pytest-discovery bypass
  shortcuts (§29) cannot turn a failure into a pass.
- **Structural violations are rejected before any execution.** Modifying a
  protected path (``tests/``, ``private/``), touching too many files, or an
  oversized patch is a STRUCTURAL_VIOLATION (§30).
- **Withdrawn generators are refused.** A challenge produced by REPO generator
  0.1.0 (whose verifier semantics allowed candidate-side expected-value
  access) is refused with WITHDRAWN_GENERATOR — it is never reinterpreted
  under 0.2.0 semantics.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from vica.protocol.models import ErrorCode
from vica.repo.generator import (
    GENERATOR_VERSION,
    TYPE_NAME,
    VERIFIER_SECRET_KEY,
    generate,
    generate_with_solution,
    hidden_tests_for,
)
from vica.repo.patch import (
    PatchError,
    apply_patch,
    parse_changed_paths,
    patch_summary,
    structural_error,
)
from vica.repo.workspace import WorkspaceError, materialize_workspace
from vica.sandbox.runner import SandboxLimits, run_sandboxed
from vica.verifier.interfaces import EvaluationResult
from vica.verifier.material import verifier_material_commitment

# Sandbox envelope for running the patched (untrusted) workspace.
REPO_SANDBOX_LIMITS = SandboxLimits(
    cpu_seconds=2.0,
    wall_seconds=10.0,
    memory_bytes=256 * 1024 * 1024,
    max_processes=16,
    max_fds=64,
    max_output_bytes=64 * 1024,
    max_file_bytes=1024 * 1024,
)

# Reads ONLY the case inputs (args) from stdin, runs ``solution.solve(*args)``
# for each, and writes the per-case ACTUAL outputs to a file given by argv[1].
# The expected values are never sent to this process: the parent compares
# actuals against expected. The driver loads ``solution.py`` from the explicit
# workspace path (argv[2]) instead of ``import solution`` so it works in
# Python isolated mode (-I) and so a patched ``solution`` that tampers with
# ``sys.modules`` cannot rewire this loader. The driver runs in a separate
# subprocess from the verifier, so candidate frames can never reach
# verifier-owned expected values and candidate ``builtins``/``json`` patches
# cannot affect the parent's comparison.
# The subprocess protocol is: parent -> stdin (ONLY inputs) -> child runs
# ``solution.solve`` -> child writes ACTUAL outputs -> parent compares. The
# expected values are never sent here. The driver captures its own ``json``
# references BEFORE loading the untrusted ``solution`` module, so a patched
# ``solve`` that rebinds ``json.dump``/``json.load`` cannot corrupt the
# result channel. ``json.load`` on stdin also happens before the module load.
_DRIVER = (
    "import importlib.util, json, sys\n"
    "_json_load = json.load\n"
    "_json_dumps = json.dumps\n"
    "_json_dump = json.dump\n"
    "spec = importlib.util.spec_from_file_location('solution', sys.argv[2])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "cases = _json_load(sys.stdin)['cases']\n"
    "actuals = []\n"
    "for c in cases:\n"
    "    try:\n"
    "        value = module.solve(*c['args'])\n"
    "    except Exception:\n"
    "        actuals.append({'ok': False, 'reason': 'exception'})\n"
    "        continue\n"
    "    try:\n"
    "        _json_dumps(value)\n"
    "    except Exception:\n"
    "        actuals.append({'ok': False, 'reason': 'not_serializable'})\n"
    "        continue\n"
    "    actuals.append({'ok': True, 'value': value})\n"
    "with open(sys.argv[1], 'w') as f:\n"
    "    _json_dump(actuals, f)\n"
)


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def repo_result_metadata(
    challenge: dict[str, Any], candidate: Any, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Enrich a ResultRecord's metadata with non-secret REPO facts (§48).

    Records ``workspace_hash``, ``task_kind``, and (for a patch candidate) the
    ``patch_hash`` / ``patch_bytes`` / ``changed_files`` / ``changed_lines``.
    Never includes the hidden tests, the reference patch, or the verifier
    secret. For non-REPO challenges the metadata is returned unchanged.
    """
    if challenge.get("type") != TYPE_NAME:
        return metadata
    meta = dict(metadata)
    payload = challenge.get("payload")
    if isinstance(payload, dict):
        if isinstance(payload.get("workspace_hash"), str):
            meta["workspace_hash"] = payload["workspace_hash"]
        if isinstance(payload.get("task_kind"), str):
            meta["task_kind"] = payload["task_kind"]
        if isinstance(payload.get("template"), str):
            meta["template"] = payload["template"]
    if isinstance(candidate, dict) and isinstance(candidate.get("patch"), str):
        meta.update(patch_summary(candidate["patch"]))
    return meta


def _run_cases(
    workspace: str | Path,
    cases: list[dict[str, Any]],
    limits: SandboxLimits,
) -> tuple[list[bool] | None, list[bool]]:
    """Run every case against the patched ``solution`` in the sandbox.

    The candidate subprocess receives ONLY the inputs; it returns the actual
    outputs and the parent compares them to the expected values.

    Returns ``(test_ok, candidate_failed)`` where ``test_ok`` is ``None`` when
    the subprocess itself failed (timeout, output overflow, launch failure, or
    unparseable result) — which the caller maps to SANDBOX_ERROR, never to a
    test failure — and otherwise a per-case boolean of ``actual == expected``.
    ``candidate_failed`` marks cases where the candidate ``solve`` crashed or
    produced a non-JSON-serializable result: those are candidate PROCESS
    failures, not test comparison failures.
    """
    with tempfile.TemporaryDirectory() as tmp:
        outfile = Path(tmp) / "out.json"
        result = run_sandboxed(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                _DRIVER,
                str(outfile),
                str(Path(workspace) / "solution.py"),
            ],
            stdin=json.dumps(
                {"cases": [{"args": c["args"]} for c in cases]}
            ),
            cwd=str(workspace),
            limits=limits,
        )
        if result.error_code is not None or result.returncode != 0:
            return None, []
        try:
            data = json.loads(outfile.read_text())
        except Exception:
            return None, []
        if not isinstance(data, list) or len(data) != len(cases):
            return None, []
        results: list[bool] = []
        candidate_failed: list[bool] = []
        for actual, case in zip(data, cases, strict=True):
            if not isinstance(actual, dict) or not actual.get("ok"):
                candidate_failed.append(True)
                results.append(False)
                continue
            candidate_failed.append(False)
            results.append(actual.get("value") == case["expected"])
        return results, candidate_failed


def _resolve_challenge(challenge: Any) -> tuple[dict[str, Any], str, int, str | None]:
    """Normalize a challenge into (payload, seed, difficulty, verifier_secret).

    The verifier secret is read from ``challenge[VERIFIER_SECRET_KEY]`` when the
    authoritative verifier injected it (``verify_submission``). Solver-facing
    challenge dicts never carry it, so only the authority can regenerate the
    hidden tests.
    """
    if not isinstance(challenge, dict):
        raise TypeError("challenge must be a dict")
    secret = challenge.get(VERIFIER_SECRET_KEY)
    secret = str(secret) if isinstance(secret, str) and secret else None
    payload = challenge.get("payload")
    if not isinstance(payload, dict):
        raise TypeError("not a repo-v0.1 payload")
    seed = str(challenge.get("seed") or "")
    difficulty = int(challenge.get("difficulty") or 0)
    return payload, seed, difficulty, secret


class RepoV01:
    """REPO-v0.1 ChallengeFamily: workspace generator + deterministic verifier."""

    type_name = TYPE_NAME
    generator_version = GENERATOR_VERSION
    # The reference patch and the hidden tests are secret-bound: a complete,
    # solver-usable challenge (workspace + public expected outputs) can only be
    # assembled by an authority holding the verifier secret.
    requires_verifier_secret = True

    def generate(self, seed: str, difficulty: int) -> dict[str, Any]:
        return generate(seed, difficulty)

    def generate_with_solution(
        self, seed: str, difficulty: int, verifier_secret: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Authoritative assembly (see :mod:`vica.repo.generator`)."""
        return generate_with_solution(seed, difficulty, verifier_secret)

    def verify(self, challenge: Any, candidate: Any) -> bool:
        return self.evaluate(challenge, candidate).valid

    def score(self, challenge: Any, candidate: Any) -> float:
        return self.evaluate(challenge, candidate).score

    def evaluate(self, challenge: Any, candidate: Any) -> EvaluationResult:
        """Single authoritative pass: validity + score computed exactly once."""
        fail = self._verify(challenge, candidate)
        valid = fail is None
        return EvaluationResult(valid=valid, score=1.0 if valid else 0.0, error_code=fail)

    def failure_code(self, challenge: Any, candidate: Any) -> ErrorCode | None:
        return self._verify(challenge, candidate)

    def _verify(self, challenge: Any, candidate: Any) -> ErrorCode | None:
        try:
            payload, seed, difficulty, secret = _resolve_challenge(challenge)
        except (TypeError, ValueError, KeyError):
            return ErrorCode.INVALID_SCHEMA

        # Historical generator semantics are withdrawn: REPO generator 0.1.0
        # verified candidates in the verifier's own interpreter, allowing
        # expected-value access from candidate frames. Such challenges are
        # refused outright, never reinterpreted under 0.2.0 semantics.
        gen_version = challenge.get("generator_version")
        if not isinstance(gen_version, str) or gen_version != GENERATOR_VERSION:
            return ErrorCode.WITHDRAWN_GENERATOR

        # Candidate must be a patch artifact.
        if not isinstance(candidate, dict) or not isinstance(candidate.get("patch"), str):
            return ErrorCode.INVALID_SCHEMA
        patch = candidate["patch"]

        # Generic structural checks (size, protected tests/, .git, binary, ...).
        code = structural_error(candidate)
        if code is not None:
            return code

        # Payload-declared allowed/forbidden path constraints (§28).
        constraints = payload.get("constraints")
        if isinstance(constraints, dict):
            allowed = constraints.get("allowed_paths")
            forbidden = constraints.get("forbidden_paths")
            if allowed:
                for path in parse_changed_paths(patch):
                    if not any(path == a or path.startswith(a.rstrip("/") + "/") for a in allowed):
                        return ErrorCode.STRUCTURAL_VIOLATION
            if forbidden:
                for path in parse_changed_paths(patch):
                    if any(path.startswith(f) for f in forbidden):
                        return ErrorCode.STRUCTURAL_VIOLATION

        # Verifier-material binding: the secret must reproduce the commitment
        # the challenge was built with, or this is an evaluator error (§27).
        commitment = challenge.get("verifier_material_commitment")
        if commitment is not None:
            if secret is None:
                return ErrorCode.INTERNAL_ERROR
            if verifier_material_commitment(secret) != commitment:
                return ErrorCode.INTERNAL_ERROR

        manifest = payload.get("workspace_manifest")
        files = payload.get("workspace_files")
        if not isinstance(manifest, list) or not isinstance(files, dict):
            return ErrorCode.INTERNAL_ERROR

        public_tests = payload.get("public_tests")
        if not isinstance(public_tests, list) or not public_tests:
            return ErrorCode.INTERNAL_ERROR

        try:
            with tempfile.TemporaryDirectory(prefix="vica-repo-verify-") as tmp:
                ws = materialize_workspace(
                    manifest,
                    {k: _to_bytes(v) for k, v in files.items()},
                    Path(tmp) / "ws",
                )
                try:
                    apply_patch(ws, patch)
                except PatchError:
                    return ErrorCode.PATCH_APPLY_FAILURE

                public_results, public_failed = _run_cases(ws, public_tests, REPO_SANDBOX_LIMITS)
                if public_results is None:
                    return ErrorCode.SANDBOX_ERROR
                if any(public_failed):
                    return ErrorCode.PROCESS_FAILURE
                if not all(public_results):
                    return ErrorCode.PUBLIC_TEST_FAILURE

                # Hidden material is only available to the authoritative verifier.
                if secret is None:
                    return ErrorCode.INTERNAL_ERROR
                try:
                    hidden = hidden_tests_for(seed, difficulty, secret)
                except (ValueError, RuntimeError):
                    return ErrorCode.INTERNAL_ERROR
                hidden_results, hidden_failed = _run_cases(ws, hidden, REPO_SANDBOX_LIMITS)
                if hidden_results is None:
                    return ErrorCode.SANDBOX_ERROR
                if any(hidden_failed):
                    return ErrorCode.PROCESS_FAILURE
                if not all(hidden_results):
                    return ErrorCode.HIDDEN_TEST_FAILURE
        except WorkspaceError:
            return ErrorCode.INTERNAL_ERROR
        except Exception:
            return ErrorCode.INTERNAL_ERROR
        return None


FAMILY = RepoV01()

# Stable, descriptive alias for the REPO challenge type id (used by reverify
# binding and other modules that must not import the generator internals).
REPO_TYPE_NAME = TYPE_NAME

__all__ = [
    "FAMILY",
    "REPO_SANDBOX_LIMITS",
    "REPO_TYPE_NAME",
    "RepoV01",
]