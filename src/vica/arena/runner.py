"""Benchmark runner: challenge generation, solving, verification, recording.

Per docs/SPEC.md section 8 the runner:
1. generates challenges
2. starts timers
3. calls the solver system
4. collects the candidate
5. calls the verifier
6. records verify time
7. saves the raw result
8. aggregates metrics

The runner never modifies solver output, never uses an LLM judge, and does
not implicitly retry (retries are a strategy decision of the system).

Evaluation Mode boundary (docs/SPEC.md "Verifier material"): one verifier
secret is authoritative per experiment. It is never written into a
solver-visible challenge, never stored in the experiment database, and never
passed to a solver. The database keeps only a public material reference
(id + version); the secret itself lives in the verifier-private path
(``.vica/private/``) or is provided by the evaluator via
``VICA_VERIFIER_SECRET``. Adversarial evaluation must run solvers in a
workspace that does not contain the verifier-private material.
"""

from __future__ import annotations

import hashlib
import os
import platform
import secrets
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vica import __version__
from vica.challenges.opt_v01.family import score_order
from vica.challenges.registry import available_types, build_challenge
from vica.protocol.models import (
    CandidateSubmission,
    Challenge,
    ErrorCode,
    RunRecord,
    SolveOutput,
)
from vica.protocol.serialization import canonical_json_bytes
from vica.storage.db import Storage
from vica.systems.llm.llm_solver import (
    LLMSolverSystem,
    SynthLLMAgentSystem,
    SynthLLMOneShotSystem,
)
from vica.systems.opt.brute import BruteOptSystem
from vica.systems.opt.dp import DpOptSystem, optimal_order
from vica.systems.opt.edd import EddSystem
from vica.systems.opt.random_order import RandomOrderSystem
from vica.systems.random.random_search import RandomSearchSystem
from vica.systems.solver.z3_solver import Z3SolverSystem
from vica.systems.synth.brute_force import BruteForceSynthSystem
from vica.systems.synth.random_program import RandomProgramSystem
from vica.verifier.verifier import verify_submission

SYSTEM_FACTORIES: dict[str, Any] = {
    "random": lambda: RandomSearchSystem(),
    "z3": lambda: Z3SolverSystem(),
    "llm": lambda: LLMSolverSystem(),
    "llm-one-shot": lambda: SynthLLMOneShotSystem(),
    "llm-agent": lambda: SynthLLMAgentSystem(),
    "synth-random": lambda: RandomProgramSystem(),
    "synth-brute": lambda: BruteForceSynthSystem(),
    "opt-random": lambda: RandomOrderSystem(),
    "opt-edd": lambda: EddSystem(),
    "opt-brute": lambda: BruteOptSystem(),
    "opt-dp": lambda: DpOptSystem(),
}

# Derivation scheme for secret-bound verifier material
# (target seed + hidden test seed, HMAC-SHA256, domain-separated tags).
VERIFIER_MATERIAL_VERSION = "synth-v0.1-hmac-sha256-target-hidden:v1"


def available_systems() -> list[str]:
    return sorted(SYSTEM_FACTORIES)


def supported_challenge_types(system_name: str) -> list[str]:
    """Capability contract: which challenge types *system_name* can solve.

    Systems declare ``supported_challenge_types``; the runner fail-fasts at
    experiment start when a configured pairing is incompatible (a configuration
    error, never recorded as a solver failure).
    """
    factory = SYSTEM_FACTORIES[system_name]
    try:
        system = factory()
    except Exception as exc:
        raise ValueError(
            f"system {system_name!r} cannot be constructed: {exc} "
            "(check environment configuration such as VICA_LLM_MODEL)"
        ) from exc
    supported = getattr(system, "supported_challenge_types", None)
    if supported is None:
        raise ValueError(
            f"system {system_name!r} does not declare supported_challenge_types"
        )
    return sorted(supported)


def _validate_pairings(challenge_type: str, systems: list[str]) -> None:
    """Fail fast on incompatible (challenge_type, system) pairs.

    An incompatible pairing is an experiment configuration error: no RunRecord
    is written. Runs that produce INTERNAL_ERROR because a solver cannot even
    interpret the challenge must not become official benchmark data.
    """
    for name in systems:
        supported = supported_challenge_types(name)
        if challenge_type not in supported:
            raise ValueError(
                f"system {name!r} does not support challenge {challenge_type!r}; "
                f"supported: {supported}"
            )


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _environment_manifest() -> dict[str, Any]:
    """Lightweight reproducibility manifest (SPEC "Reproducibility").

    Records the interpreter / OS / git / relevant dependency versions. Never
    includes credentials or API keys.
    """
    z3_version: str | None = None
    try:
        import z3

        z3_version = z3.get_version_string()
    except Exception:  # pragma: no cover - optional dependency
        z3_version = None
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "vica_version": __version__,
        "git_commit": git_commit(),
        "z3_version": z3_version,
    }


def _save_system_configs(
    storage: Storage, experiment_id: str, systems: list[str]
) -> None:
    """Persist each system's resolved configuration for one experiment.

    System configs are experiment-scoped (``experiment_systems`` table): every
    experiment keeps its own resolved snapshot, so historical runs stay
    reproducible and are never overwritten by a later experiment. Only safe,
    non-secret fields are recorded (SPEC "System config must be persisted").
    Credentials are never part of a system's ``config()``.
    """
    for name in systems:
        try:
            config = SYSTEM_FACTORIES[name]().config()
        except Exception as exc:  # pragma: no cover - defensive
            config = {"error": str(exc)}
        storage.save_system_config(
            experiment_id=experiment_id, system_id=name, type_=name, config=config
        )


def _verifier_secret_for(db_path: str, experiment_id: str) -> tuple[str, str]:
    """Resolve the experiment verifier secret and its public material id.

    The evaluator may fix the secret via ``VICA_VERIFIER_SECRET`` (same secret
    + same seed + same version => same target and hidden tests, enabling
    cross-machine reproducibility). Otherwise a fresh secret is drawn and
    persisted to the verifier-private path next to the database
    (``<db>.private/<experiment_id>.material.json``, mode 0600). The secret is
    never stored in the experiment database; only the material id/version are.
    """
    version = VERIFIER_MATERIAL_VERSION
    secret = os.environ.get("VICA_VERIFIER_SECRET")
    if secret:
        material_id = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
        return secret, material_id
    secret = secrets.token_hex(32)
    material_id = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
    private_dir = Path(db_path).parent / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    material_path = private_dir / f"{experiment_id}.material.json"
    material = {
        "experiment_id": experiment_id,
        "verifier_material_id": material_id,
        "verifier_material_version": version,
        "verifier_secret": secret,
    }
    material_path.write_text(canonical_json_bytes(material).decode("utf-8"))
    try:
        material_path.chmod(0o600)
    except OSError:  # pragma: no cover - non-POSIX filesystems
        pass
    return secret, material_id


def _all_difficulty_systems(difficulty_systems: dict[int, list[str]] | None) -> set[str]:
    """Flatten per-difficulty system overrides into the full system set."""
    extras: set[str] = set()
    if difficulty_systems:
        for extra in difficulty_systems.values():
            extras.update(extra)
    return extras


def run_benchmark(
    *,
    challenge_type: str,
    difficulties: list[int],
    systems: list[str],
    instances: int,
    seed: int,
    db_path: str,
    experiment_id: str | None = None,
    difficulty_systems: dict[int, list[str]] | None = None,
) -> str:
    """Run a full benchmark experiment and store everything in SQLite.

    ``systems`` is the set that runs on every difficulty. ``difficulty_systems``
    overrides the system set for specific difficulties (e.g. drop an expensive
    baseline above a size threshold). Returns the experiment id.

    Fail-fast: incompatible (challenge_type, system) pairs raise ``ValueError``
    before anything is written — such a pairing is an experiment configuration
    error, not a solver outcome, so no RunRecord is produced.
    """
    if challenge_type not in available_types():
        raise ValueError(
            f"unknown challenge type {challenge_type!r}; available: {available_types()}"
        )
    requested = set(systems)
    if difficulty_systems:
        for extra in difficulty_systems.values():
            requested.update(extra)
    unknown = requested - set(available_systems())
    if unknown:
        raise ValueError(f"unknown system(s): {sorted(unknown)}; available: {available_systems()}")
    _validate_pairings(challenge_type, sorted(requested))

    experiment_id = experiment_id or f"exp-{uuid.uuid4().hex[:12]}"
    verifier_secret, material_id = _verifier_secret_for(db_path, experiment_id)
    storage = Storage(db_path)
    try:
        config = {
            "challenge_type": challenge_type,
            "difficulties": difficulties,
            "systems": systems,
            "difficulty_systems": difficulty_systems,
            "instances": instances,
            "seed": seed,
            # The active verifier secret is NEVER stored in the database. Only
            # a public reference is kept; the secret lives in the verifier-
            # private path (or is evaluator-provided via VICA_VERIFIER_SECRET).
            # Solver workspaces must not contain the verifier-private material.
            "verifier_material_id": material_id,
            "verifier_material_version": VERIFIER_MATERIAL_VERSION,
        }
        storage.save_experiment(
            experiment_id=experiment_id,
            config=config,
            created_at=_utcnow(),
            git_commit=git_commit(),
            vica_version=__version__,
            environment=_environment_manifest(),
        )
        system_set = sorted(set(systems) | _all_difficulty_systems(difficulty_systems))
        _save_system_configs(storage, experiment_id, system_set)

        start_all = time.perf_counter()
        for difficulty in difficulties:
            syss: list[str] = systems
            if difficulty_systems and difficulty in difficulty_systems:
                syss = difficulty_systems[difficulty]
            for i in range(instances):
                challenge = build_challenge(
                    challenge_type,
                    f"{seed}:{difficulty}:{i}",
                    difficulty,
                    verifier_secret=verifier_secret,
                )
                storage.save_challenge(challenge, _utcnow())
                # OPT-v0.1: the exact bitmask DP reference (O(n*2^n)) is
                # computed once per challenge, not once per (challenge, system).
                opt_reference = _opt_optimal_score(challenge)

                for system_name in syss:
                    run = _run_one(
                        storage,
                        experiment_id,
                        challenge,
                        system_name,
                        verifier_secret,
                        opt_reference=opt_reference,
                    )
                    storage.save_run(run, _utcnow())

        print(
            f"experiment {experiment_id}: {len(difficulties)} difficulties x "
            f"{instances} instances x {len(systems)} systems in "
            f"{time.perf_counter() - start_all:.1f}s"
        )
        return experiment_id
    finally:
        storage.close()


def _opt_optimal_score(challenge: Challenge) -> float | None:
    """Exact optimal score for an OPT-v0.1 payload (deltas vs reference).

    Uses the deterministic bitmask DP (``opt-dp``) as the optimal-score
    reference; returns None for non-OPT challenges. The value is attached to
    run metadata so metrics can compute regret without re-solving.
    """
    if challenge.type != "opt-v0.1":
        return None
    payload = challenge.payload
    processing = payload.get("processing")
    deadlines = payload.get("deadlines")
    if not isinstance(processing, list) or not isinstance(deadlines, list):
        return None
    return float(score_order(processing, deadlines, optimal_order(processing, deadlines)))


def _run_one(
    storage: Storage,
    experiment_id: str,
    challenge: Challenge,
    system_name: str,
    verifier_secret: str,
    *,
    opt_reference: float | None,
) -> RunRecord:
    """Solve one challenge with one system, returning a RunRecord.

    Exceptions from the system are isolated and recorded as INTERNAL_ERROR
    runs rather than aborting the whole benchmark.
    """
    factory = SYSTEM_FACTORIES[system_name]
    try:
        system = factory()
    except Exception as exc:
        return _failure_record(
            experiment_id,
            challenge,
            system_name,
            ErrorCode.INTERNAL_ERROR,
            {},
            0.0,
            str(exc),
        )

    challenge_dict = challenge.model_dump()
    solve_start = time.perf_counter()
    try:
        output = system.solve(challenge_dict)
        solve_ms = (time.perf_counter() - solve_start) * 1000.0
        if not isinstance(output, SolveOutput):
            raise TypeError(f"system {system_name} did not return a SolveOutput")
    except Exception as exc:
        solve_ms = (time.perf_counter() - solve_start) * 1000.0
        return _failure_record(
            experiment_id, challenge, system_name, ErrorCode.INTERNAL_ERROR, {}, solve_ms, str(exc)
        )

    candidate = output.candidate
    if candidate is None:
        # Distinguish an explicit solver timeout and provider/transport
        # failures from genuinely wrong/no candidate (SPEC "Solver timeout
        # semantics", "LLM transport error semantics"). Timeouts and provider
        # errors are resource/transport outcomes, never "the model was wrong".
        status = output.metadata.get("status")
        if status == "timeout":
            return _failure_record(
                experiment_id,
                challenge,
                system_name,
                ErrorCode.TIMEOUT,
                output.metadata,
                solve_ms,
                "solver timed out without producing a candidate",
            )
        if status in ("transport_error", "provider_error"):
            return _failure_record(
                experiment_id,
                challenge,
                system_name,
                ErrorCode.INTERNAL_ERROR,
                output.metadata,
                solve_ms,
                f"provider/transport failure without a candidate (status={status})",
            )
        return _failure_record(
            experiment_id,
            challenge,
            system_name,
            ErrorCode.INVALID_SOLUTION,
            output.metadata,
            solve_ms,
            "no candidate produced",
        )

    metadata = dict(output.metadata)
    if opt_reference is not None:
        metadata["optimal_score"] = opt_reference

    submission = CandidateSubmission(
        challenge_id=challenge.id,
        system_id=system_name,
        candidate=candidate,
        metadata=metadata,
    )
    result = verify_submission(challenge, submission, verifier_secret=verifier_secret)
    if result.valid and opt_reference is not None:
        metadata["regret"] = opt_reference - result.score

    return RunRecord(
        experiment_id=experiment_id,
        challenge_id=challenge.id,
        challenge_type=challenge.type,
        generator_version=challenge.generator_version,
        difficulty=challenge.difficulty,
        seed=challenge.seed,
        system_id=system_name,
        candidate=candidate,
        valid=result.valid,
        score=result.score,
        solve_wall_time_ms=solve_ms,
        verify_time_us=result.verify_time_us,
        error_code=result.error_code,
        metadata=metadata,
    )


def _failure_record(
    experiment_id: str,
    challenge: Challenge,
    system_name: str,
    error_code: ErrorCode,
    metadata: dict[str, Any],
    solve_ms: float,
    error_msg: str,
) -> RunRecord:
    metadata = dict(metadata)
    metadata["error"] = error_msg
    return RunRecord(
        experiment_id=experiment_id,
        challenge_id=challenge.id,
        challenge_type=challenge.type,
        generator_version=challenge.generator_version,
        difficulty=challenge.difficulty,
        seed=challenge.seed,
        system_id=system_name,
        candidate=None,
        valid=False,
        score=0.0,
        solve_wall_time_ms=solve_ms,
        verify_time_us=0,
        error_code=error_code,
        metadata=metadata,
    )


__all__ = [
    "SYSTEM_FACTORIES",
    "VERIFIER_MATERIAL_VERSION",
    "available_systems",
    "git_commit",
    "run_benchmark",
    "supported_challenge_types",
]