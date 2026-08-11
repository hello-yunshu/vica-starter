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


if __name__ == "__main__":
    app()