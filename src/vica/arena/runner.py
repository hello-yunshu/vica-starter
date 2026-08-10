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
"""

from __future__ import annotations

import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from vica import __version__
from vica.challenges.registry import available_types, build_challenge
from vica.protocol.models import (
    CandidateSubmission,
    Challenge,
    ErrorCode,
    RunRecord,
    SolveOutput,
)
from vica.storage.db import Storage
from vica.systems.llm.llm_solver import LLMSolverSystem
from vica.systems.opt.brute import BruteOptSystem
from vica.systems.opt.dp import DpOptSystem
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
    "synth-random": lambda: RandomProgramSystem(),
    "synth-brute": lambda: BruteForceSynthSystem(),
    "opt-random": lambda: RandomOrderSystem(),
    "opt-edd": lambda: EddSystem(),
    "opt-brute": lambda: BruteOptSystem(),
    "opt-dp": lambda: DpOptSystem(),
}


def available_systems() -> list[str]:
    return sorted(SYSTEM_FACTORIES)


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

    experiment_id = experiment_id or f"exp-{uuid.uuid4().hex[:12]}"
    storage = Storage(db_path)
    try:
        config = {
            "challenge_type": challenge_type,
            "difficulties": difficulties,
            "systems": systems,
            "difficulty_systems": difficulty_systems,
            "instances": instances,
            "seed": seed,
        }
        storage.save_experiment(
            experiment_id=experiment_id,
            config=config,
            created_at=_utcnow(),
            git_commit=git_commit(),
            vica_version=__version__,
        )

        start_all = time.perf_counter()
        for difficulty in difficulties:
            syss: list[str] = systems
            if difficulty_systems and difficulty in difficulty_systems:
                syss = difficulty_systems[difficulty]
            for i in range(instances):
                challenge = build_challenge(
                    challenge_type, f"{seed}:{difficulty}:{i}", difficulty
                )
                storage.save_challenge(challenge, _utcnow())

                for system_name in syss:
                    run = _run_one(storage, experiment_id, challenge, system_name)
                    storage.save_run(run, _utcnow())

        print(
            f"experiment {experiment_id}: {len(difficulties)} difficulties x "
            f"{instances} instances x {len(systems)} systems in "
            f"{time.perf_counter() - start_all:.1f}s"
        )
        return experiment_id
    finally:
        storage.close()


def _run_one(
    storage: Storage,
    experiment_id: str,
    challenge: Challenge,
    system_name: str,
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
        return _failure_record(
            experiment_id,
            challenge,
            system_name,
            ErrorCode.INVALID_SOLUTION,
            output.metadata,
            solve_ms,
            "no candidate produced",
        )

    submission = CandidateSubmission(
        challenge_id=challenge.id,
        system_id=system_name,
        candidate=candidate,
        metadata=output.metadata,
    )
    result = verify_submission(challenge, submission)

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
        metadata=output.metadata,
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
    "available_systems",
    "git_commit",
    "run_benchmark",
]