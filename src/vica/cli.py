"""VICA command-line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from vica.arena.export import write_metrics_csv, write_runs_csv, write_runs_json
from vica.arena.leaderboard import format_leaderboard, leaderboard_rows
from vica.arena.runner import available_systems, run_benchmark
from vica.challenges.registry import available_types
from vica.storage.db import Storage

app = typer.Typer(
    help="VICA — Verifiable Intelligence Compute Arena",
    no_args_is_help=True,
)

# Default DB lives under a gitignored `.vica/` dir so a fresh clone does not
# accumulate a runtime artifact in the repo root (see docs/SPEC.md "Storage").
DEFAULT_DB = Path(".vica/vica.db")


@app.command()
def version() -> None:
    """Print the installed VICA version."""
    from vica import __version__

    typer.echo(__version__)


@app.command()
def benchmark(
    challenge: Annotated[str, typer.Option(help="challenge type")] = "csp-v0.1",
    difficulty: Annotated[
        str, typer.Option(help="difficulty preset(s); e.g. 3 or 1-5 or 1,3,5")
    ] = "1-3",
    systems: Annotated[
        str, typer.Option(help="comma-separated system ids")
    ] = "random,z3",
    instances: Annotated[int, typer.Option(min=1, help="instances per difficulty")] = 1000,
    seed: Annotated[int, typer.Option(help="experiment seed")] = 42,
    db: Annotated[Path, typer.Option(help="SQLite database path")] = DEFAULT_DB,
) -> None:
    """Run a benchmark experiment and store results in SQLite."""
    if challenge not in available_types():
        typer.echo(
            f"error: unknown challenge type {challenge!r}; available: {available_types()}",
            err=True,
        )
        raise typer.Exit(1)
    requested = [s.strip() for s in systems.split(",") if s.strip()]
    unknown = set(requested) - set(available_systems())
    if unknown:
        typer.echo(
            f"error: unknown system(s) {sorted(unknown)}; available: {available_systems()}",
            err=True,
        )
        raise typer.Exit(1)

    try:
        difficulties = _parse_difficulties(difficulty)
    except ValueError as exc:
        typer.echo(f"error: invalid difficulty spec {difficulty!r}: {exc}", err=True)
        raise typer.Exit(1) from exc
    if not difficulties:
        typer.echo("error: no difficulties parsed", err=True)
        raise typer.Exit(1)

    try:
        experiment_id = run_benchmark(
            challenge_type=challenge,
            difficulties=difficulties,
            systems=requested,
            instances=instances,
            seed=seed,
            db_path=str(db),
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"experiment id: {experiment_id}")
    typer.echo("run 'vica report <experiment-id>' to see metrics.")


@app.command()
def report(
    experiment_id: Annotated[str, typer.Argument(help="experiment id")],
    db: Annotated[Path, typer.Option(help="SQLite database path")] = DEFAULT_DB,
) -> None:
    """Print aggregate metrics for an experiment."""
    storage = Storage(db)
    try:
        records = storage.runs_to_records(experiment_id)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        storage.close()

    if not records:
        typer.echo(f"no runs found for experiment {experiment_id}")
        raise typer.Exit(1)

    from vica.arena.leaderboard import format_optional_metric
    from vica.arena.metrics import aggregate

    cells = aggregate(records)
    typer.echo("metrics:")
    for (system_id, difficulty), m in sorted(cells.items()):
        typer.echo(
            f"  {system_id:<10} d={difficulty:<3} "
            f"success={m.success_rate:.3f}  mean_ms={m.mean_solve_ms:8.1f}  "
            f"p50={m.p50_solve_ms:7.1f}  p95={m.p95_solve_ms:7.1f}  "
            f"verify_us={m.mean_verify_us:6.1f}  "
            f"cost=${format_optional_metric(m.total_cost_usd, '.5f')}  "
            f"$/sol={format_optional_metric(m.cost_per_valid_solution, '.5f')}  "
            f"SPD={format_optional_metric(m.valid_solutions_per_dollar, '.2f')}  "
            f"regret={format_optional_metric(m.mean_regret, '.4f')}  "
            f"SPS={m.valid_solutions_per_second:.2f}"
        )


@app.command()
def leaderboard(
    experiment_id: Annotated[str, typer.Argument(help="experiment id")],
    db: Annotated[Path, typer.Option(help="SQLite database path")] = DEFAULT_DB,
) -> None:
    """Print the multi-system leaderboard for an experiment."""
    storage = Storage(db)
    try:
        records = storage.runs_to_records(experiment_id)
    finally:
        storage.close()
    rows = leaderboard_rows(records)
    typer.echo(format_leaderboard(rows))


@app.command()
def export(
    experiment_id: Annotated[str, typer.Argument(help="experiment id")],
    kind: Annotated[str, typer.Option(help="runs | metrics")] = "runs",
    format: Annotated[str, typer.Option(help="csv | json")] = "csv",
    out: Annotated[Path, typer.Option(help="output file (default: stdout)")] = Path("-"),
    db: Annotated[Path, typer.Option(help="SQLite database path")] = DEFAULT_DB,
) -> None:
    """Export runs or metrics as CSV / JSON."""
    storage = Storage(db)
    try:
        records = storage.runs_to_records(experiment_id)
    finally:
        storage.close()

    handle = sys.stdout if str(out) == "-" else out.open("w", newline="")
    try:
        if kind == "runs" and format == "csv":
            write_runs_csv(records, handle)
        elif kind == "runs" and format == "json":
            write_runs_json(records, handle)
        elif kind == "metrics" and format == "csv":
            write_metrics_csv(records, handle)
        else:
            raise typer.BadParameter("expected kind=runs|metrics and format=csv|json")
    finally:
        if handle is not sys.stdout:
            handle.close()


def _parse_difficulties(spec: str) -> list[int]:
    levels: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo_s, hi_s = token.split("-", 1)
            levels.extend(range(int(lo_s), int(hi_s) + 1))
        else:
            levels.append(int(token))
    return sorted(set(levels))


@app.command()
def challenges() -> None:
    """List available challenge types and systems."""
    from vica.challenges import csp_v01, opt_v01, synth_v01

    typer.echo("challenge types:")
    for t in available_types():
        typer.echo(f"  {t}")

    # Difficulty presets per family (each family module exports its own).
    presets_by_type: dict[str, dict[int, Any]] = {
        csp_v01.TYPE_NAME: csp_v01.DIFFICULTY_PRESETS,
        synth_v01.TYPE_NAME: synth_v01.DIFFICULTY_PRESETS,
        opt_v01.TYPE_NAME: opt_v01.DIFFICULTY_PRESETS,
    }
    for type_name, presets in presets_by_type.items():
        if type_name not in available_types():
            continue
        # Normalize dataclass / tuple presets to plain dicts for JSON.
        serializable = {
            str(k): (v if isinstance(v, (dict, list, tuple, str, int, float, bool)) else v.__dict__)
            for k, v in presets.items()
        }
        typer.echo(f"{type_name} difficulty presets: {json.dumps(serializable, default=str)}")

    typer.echo(f"systems: {', '.join(available_systems())}")


# ------------------------------------------------------------------ v0.2 eval


eval_app = typer.Typer(
    help="v0.2 Benchmark Research & External Evaluation (docs/BENCHMARK_METHODOLOGY.md)",
    no_args_is_help=True,
)
app.add_typer(eval_app, name="eval")


@eval_app.command("prepare")
def eval_prepare(
    challenge: Annotated[str, typer.Option(help="challenge type")] = "synth-v0.1",
    difficulty: Annotated[
        str, typer.Option(help="difficulty preset(s); e.g. 1-3 or 1,3,5")
    ] = "1-3",
    instances: Annotated[int, typer.Option(min=1, help="instances per difficulty")] = 20,
    seed: Annotated[int, typer.Option(help="evaluation seed")] = 42,
    out: Annotated[Path, typer.Option(help="output directory")] = Path(
        ".vica/evaluations/eval-001"
    ),
    verifier_secret: Annotated[
        str | None,
        typer.Option(
            help="verifier secret (default: $VICA_VERIFIER_SECRET or generated)"
        ),
    ] = None,
) -> None:
    """Prepare a public+private Evaluation Bundle."""
    from vica.eval.bundle import prepare_evaluation

    try:
        difficulties = _parse_difficulties(difficulty)
    except ValueError as exc:
        typer.echo(f"error: invalid difficulty spec {difficulty!r}: {exc}", err=True)
        raise typer.Exit(1) from exc
    if not difficulties:
        typer.echo("error: no difficulties parsed", err=True)
        raise typer.Exit(1)
    try:
        summary = prepare_evaluation(
            challenge_type=challenge,
            difficulties=difficulties,
            instances=instances,
            seed=seed,
            out=out,
            verifier_secret=verifier_secret,
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"evaluation id: {summary['evaluation_id']}")
    typer.echo(f"challenges:    {summary['challenge_count']}")
    typer.echo(f"public hash:   {summary['public_manifest_hash']}")
    typer.echo(f"private hash:  {summary['private_manifest_hash']}")
    typer.echo(f"out:           {summary['out']}")


@eval_app.command("inspect")
def eval_inspect(
    bundle: Annotated[Path, typer.Argument(help="evaluation bundle directory")],
) -> None:
    """Validate an Evaluation Bundle (no solver is invoked)."""
    from vica.eval.bundle import inspect_evaluation

    try:
        info = inspect_evaluation(bundle)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"evaluation_id: {info['evaluation_id']}")
    typer.echo(f"bundle_format:  {info['bundle_format_version']}")
    typer.echo(f"challenge_type: {info['challenge_type']} ({info['generator_version']})")
    typer.echo(f"difficulties:   {info['difficulties']}")
    typer.echo(f"challenge_count:{info['challenge_count']}")
    typer.echo(f"public hash:    {info['public_manifest_hash']}")
    typer.echo(f"private hash:   {info['private_manifest_hash']}")
    typer.echo(f"commitment:     {info['verifier_material_commitment']}")
    if info["ok"]:
        typer.echo("status: OK")
    else:
        typer.echo("status: FAIL", err=True)
        for issue in info["issues"]:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(2)


@eval_app.command("verify")
def eval_verify(
    evaluation: Annotated[Path, typer.Option(help="evaluation bundle directory")],
    submission: Annotated[Path, typer.Option(help="submission bundle directory")],
    out: Annotated[Path, typer.Option(help="result bundle output directory")],
    system: Annotated[
        str | None,
        typer.Option("--system", help="system id (default: submission manifest system_id)"),
    ] = None,
    trust_runner_telemetry: Annotated[
        bool,
        typer.Option(
            "--trust-runner-telemetry",
            help="trust reserved _vica_* runner telemetry (only for a VICA "
            "command-solver artifact; never for a file-exchange submission)",
        ),
    ] = False,
) -> None:
    """Authoritatively verify a submission and write a Result Bundle."""
    from vica.eval.verify import verify_evaluation

    try:
        summary = verify_evaluation(
            evaluation=evaluation,
            submission=submission,
            out=out,
            system_id=system,
            trusted_runner_telemetry=trust_runner_telemetry,
        )
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"evaluation id: {summary['evaluation_id']}")
    typer.echo(f"system id:     {summary['system_id']}")
    typer.echo(f"challenges:    {summary['challenge_count']}")
    typer.echo(f"valid:         {summary['valid']}")
    typer.echo(f"no_submission: {summary['no_submission']}")
    typer.echo(f"bundle hash:   {summary['bundle_hash']}")
    typer.echo(f"out:           {summary['out']}")


# ------------------------------------------------------------------ v0.2 solver


solver_app = typer.Typer(
    help="v0.2 External Solver (docs/protocol/BUNDLE.md)", no_args_is_help=True
)
app.add_typer(solver_app, name="solver")


@solver_app.command("run")
def solver_run(
    command: Annotated[str, typer.Option(help="shell command to run once per challenge")],
    bundle: Annotated[Path, typer.Option(help="evaluation bundle (public) directory")],
    out: Annotated[Path, typer.Option(help="submission bundle output directory")],
    system: Annotated[str, typer.Option(help="system id")] = "external",
    timeout: Annotated[float, typer.Option(help="per-challenge timeout (seconds)")] = 120.0,
) -> None:
    """Run an external command once per challenge (stdin->challenge, stdout->candidate)."""
    from vica.eval.command_solver import solve_with_command

    try:
        summary = solve_with_command(
            evaluation=bundle,
            command=command,
            out=out,
            system_id=system,
            timeout_s=timeout,
        )
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"evaluation id: {summary['evaluation_id']}")
    typer.echo(f"system id:     {summary['system_id']}")
    typer.echo(f"solved:        {summary['solved']}/{summary['expected']}")
    typer.echo(f"failures:      {len(summary['failures'])}")
    typer.echo(f"out:           {summary['out']}")


# ------------------------------------------------------------------ v0.3 agent


agent_app = typer.Typer(
    help="v0.3 Coding-Agent benchmark (REPO workspace, docs/SPEC.md 'Agent Mode')",
    no_args_is_help=True,
)
app.add_typer(agent_app, name="agent")


@agent_app.command("run")
def agent_run(
    bundle: Annotated[Path, typer.Option(help="evaluation bundle (public) directory")],
    command: Annotated[str, typer.Option(help="agent command run once per REPO challenge")],
    out: Annotated[Path, typer.Option(help="submission bundle output directory")],
    system: Annotated[str, typer.Option(help="system id")] = "agent",
    timeout: Annotated[float, typer.Option(help="per-task timeout (seconds)")] = 300.0,
    pass_env: Annotated[
        list[str] | None,
        typer.Option(
            "--pass-env",
            help="explicitly forward an env var name to the agent (repeatable; "
            "verifier-reserved secrets are always rejected)",
        ),
    ] = None,
) -> None:
    """Run a Coding Agent once per REPO challenge and capture its patch."""
    from vica.eval.agent_runner import run_agent

    try:
        summary = run_agent(
            evaluation=bundle,
            command=command,
            out=out,
            system_id=system,
            timeout_s=timeout,
            pass_env=pass_env,
        )
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"evaluation id: {summary['evaluation_id']}")
    typer.echo(f"system id:     {summary['system_id']}")
    typer.echo(f"solved:        {summary['solved']}/{summary['expected']}")
    typer.echo(f"failures:      {len(summary['failures'])}")
    typer.echo(f"out:           {summary['out']}")


@agent_app.command("noop")
def agent_noop(
    bundle: Annotated[Path, typer.Option(help="evaluation bundle (public) directory")],
    out: Annotated[Path, typer.Option(help="submission bundle output directory")],
    system: Annotated[str, typer.Option(help="system id")] = "noop",
) -> None:
    """NoOp baseline: submit an empty patch for every REPO challenge (§40)."""
    from vica.eval.agent_runner import run_noop

    try:
        summary = run_noop(evaluation=bundle, out=out, system_id=system)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"evaluation id: {summary['evaluation_id']}")
    typer.echo(f"baseline:      {summary['baseline']}")
    typer.echo(f"out:           {summary['out']}")


@agent_app.command("reference")
def agent_reference(
    bundle: Annotated[Path, typer.Option(help="evaluation bundle (public) directory")],
    out: Annotated[Path, typer.Option(help="submission bundle output directory")],
    system: Annotated[str, typer.Option(help="system id")] = "reference",
    verifier_secret: Annotated[
        str | None,
        typer.Option(
            help="verifier secret (default: $VICA_VERIFIER_SECRET); evaluator/calibration only"
        ),
    ] = None,
) -> None:
    """Reference baseline: submit the authoritative patch for every challenge (§41)."""
    from vica.eval.agent_runner import run_reference

    try:
        summary = run_reference(
            evaluation=bundle,
            out=out,
            system_id=system,
            verifier_secret=verifier_secret or "",
        )
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"evaluation id: {summary['evaluation_id']}")
    typer.echo(f"baseline:      {summary['baseline']}")
    typer.echo(f"out:           {summary['out']}")


# ------------------------------------------------------------------ v0.2 reverify


@app.command()
def reverify(
    result_bundle: Annotated[Path, typer.Argument(help="result bundle directory")],
    evaluation: Annotated[Path, typer.Option(help="evaluation bundle root directory")],
    system: Annotated[
        str | None,
        typer.Option("--system", help="system id (default: result bundle system_id)"),
    ] = None,
) -> None:
    """Strictly reverify a Result Bundle (no solver call)."""
    from vica.eval.reverify import reverify_bundle

    try:
        summary = reverify_bundle(result_bundle, evaluation, system_id=system)
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"evaluation id: {summary['evaluation_id']}")
    typer.echo(f"system id:     {summary['system_id']}")
    typer.echo(f"challenges:    {summary['challenge_count']}")
    typer.echo(f"matched:       {summary['matched']}")
    if summary["ok"]:
        typer.echo("reverify: OK (identical valid/score/error semantics)")
    else:
        typer.echo(f"reverify: {len(summary['mismatches'])} mismatch(es)", err=True)
        raise typer.Exit(2)


if __name__ == "__main__":
    app()