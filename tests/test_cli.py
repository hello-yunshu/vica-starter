"""CLI end-to-end tests (SPEC section 13.4): report must not crash on N/A."""

from __future__ import annotations

from typer.testing import CliRunner

from vica.cli import app

runner = CliRunner()


def _run(*args: str):
    return runner.invoke(app, list(args))


def test_help() -> None:
    result = _run("--help")
    assert result.exit_code == 0
    assert "VICA" in result.output


def test_version() -> None:
    result = _run("version")
    assert result.exit_code == 0
    # Non-empty version string on a single line.
    assert result.output.strip()


def test_benchmark_report_unknown_cost_is_na(tmp_path) -> None:
    """A random (cost-UNKNOWN) benchmark must report a clean N/A, exit 0.

    ``random`` never sets ``estimated_cost_usd``, so every cost-derived metric
    is UNKNOWN. The report renderer must surface them as N/A, not crash.
    """
    db = str(tmp_path / "cli.db")
    bench = _run("benchmark", "--challenge", "csp-v0.1", "--difficulty", "1",
                 "--systems", "random", "--instances", "2", "--seed", "42",
                 "--db", db)
    assert bench.exit_code == 0, bench.output
    # Extract the experiment id from the output line.
    exp_id = None
    for line in bench.output.splitlines():
        if line.startswith("experiment id:"):
            exp_id = line.split(":", 1)[1].strip()
    assert exp_id

    rep = _run("report", exp_id, "--db", db)
    assert rep.exit_code == 0, rep.output
    assert "N/A" in rep.output
    assert "$/sol" in rep.output

    lb = _run("leaderboard", exp_id, "--db", db)
    assert lb.exit_code == 0, lb.output
    assert "N/A" in lb.output


def test_benchmark_incompatible_pairing_exits_nonzero(tmp_path) -> None:
    """z3 + synth is a configuration error: nonzero exit, no crash."""
    db = str(tmp_path / "cli2.db")
    result = _run("benchmark", "--challenge", "synth-v0.1", "--difficulty", "1",
                  "--systems", "z3", "--instances", "1", "--seed", "1", "--db", db)
    assert result.exit_code != 0
    assert "does not support challenge" in result.output


def test_report_no_runs_exits_nonzero(tmp_path) -> None:
    db = str(tmp_path / "cli3.db")
    result = _run("report", "exp-missing", "--db", db)
    assert result.exit_code != 0
    assert "no runs found" in result.output