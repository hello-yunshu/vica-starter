"""End-to-end CLI tests (docs/reports stabilization §5.2, §13.4).

Covers the full ``vica benchmark -> vica report -> vica leaderboard`` path for
systems whose ``estimated_cost_usd`` is UNKNOWN (random / z3): the report must
render ``N/A`` and exit 0, never crash on ``None`` costs.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from vica.cli import app

runner = CliRunner()


@pytest.fixture()
def db_path(tmp_path) -> str:
    return str(tmp_path / "cli.db")


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "benchmark" in result.output
    assert "report" in result.output
    assert "leaderboard" in result.output


def test_unknown_challenge_type_fails() -> None:
    result = runner.invoke(
        app, ["benchmark", "--challenge", "nope-v1", "--db", "/tmp/nope.db"]
    )
    assert result.exit_code == 1
    assert "unknown challenge type" in result.output


def test_benchmark_report_leaderboard_unknown_cost(db_path: str) -> None:
    """random/z3 have unknown costs; report/leaderboard must print N/A, exit 0."""
    result = runner.invoke(
        app, [
            "benchmark",
            "--challenge", "csp-v0.1",
            "--difficulty", "1",
            "--systems", "random,z3",
            "--instances", "2",
            "--seed", "42",
            "--db", db_path,
        ]
    )
    assert result.exit_code == 0, result.output
    assert "experiment id:" in result.output
    experiment_id = result.output.split("experiment id: ")[1].strip().split()[0]

    report = runner.invoke(app, ["report", experiment_id, "--db", db_path])
    assert report.exit_code == 0, report.output
    assert "N/A" in report.output  # UNKNOWN cost must render as N/A
    assert "metrics:" in report.output

    lb = runner.invoke(app, ["leaderboard", experiment_id, "--db", db_path])
    assert lb.exit_code == 0, lb.output
    assert "N/A" in lb.output


def test_report_missing_experiment_exits_nonzero(db_path: str) -> None:
    result = runner.invoke(app, ["report", "exp-does-not-exist", "--db", db_path])
    assert result.exit_code == 1
    assert "no runs found" in result.output


def test_study_run_reference_noop(tmp_path) -> None:
    """vica study run aggregates reference (pass) and noop (fail) over a REPO eval."""
    from vica.eval.bundle import prepare_evaluation
    from vica.repo.generator import TYPE_NAME

    eval_dir = tmp_path / "eval"
    prepare_evaluation(
        challenge_type=TYPE_NAME,
        difficulties=[1],
        instances=1,
        seed=11,
        out=eval_dir,
        verifier_secret="cli-study-secret",
    )
    systems_json = (
        '[{"system_id":"reference","kind":"reference"},'
        '{"system_id":"noop","kind":"noop"}]'
    )
    out_dir = tmp_path / "study"
    result = runner.invoke(
        app,
        [
            "study", "run",
            "--evaluation", str(eval_dir),
            "--out", str(out_dir),
            "--systems", systems_json,
            "--replicates", "1",
            "--verifier-secret", "cli-study-secret",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "task pack id:  repo-v0.1-core" in result.output
    assert "reference" in result.output
    assert "noop" in result.output
    assert (out_dir / "study.json").is_file()