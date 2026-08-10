"""Tests for the arena runner, storage, metrics, and export."""

from __future__ import annotations

import pytest

from vica.arena.export import write_metrics_csv, write_runs_csv
from vica.arena.leaderboard import leaderboard_rows
from vica.arena.metrics import aggregate
from vica.arena.runner import run_benchmark
from vica.protocol.models import RunRecord
from vica.storage.db import Storage


@pytest.fixture()
def tmp_db(tmp_path) -> str:
    return str(tmp_path / "test.db")


def test_runner_produces_records(tmp_db: str) -> None:
    experiment_id = run_benchmark(
        challenge_type="csp-v0.1",
        difficulties=[1],
        systems=["random"],
        instances=3,
        seed=7,
        db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    records = storage.runs_to_records(experiment_id)
    storage.close()
    assert len(records) == 3
    for r in records:
        assert r.challenge_type == "csp-v0.1"
        assert r.difficulty == 1
        assert r.experiment_id == experiment_id
        assert r.verify_time_us >= 0
        assert isinstance(r.valid, bool)
        assert r.system_id == "random"


def test_runner_exception_isolation(tmp_db: str) -> None:
    experiment_id = run_benchmark(
        challenge_type="csp-v0.1",
        difficulties=[1],
        systems=["random", "z3"],
        instances=2,
        seed=1,
        db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    records = storage.runs_to_records(experiment_id)
    storage.close()
    systems = {r.system_id for r in records}
    assert systems == {"random", "z3"}


def test_difficulty_systems_override(tmp_db: str) -> None:
    """difficulty_systems drops a system for specific difficulties only."""
    experiment_id = run_benchmark(
        challenge_type="synth-v0.1",
        difficulties=[1, 2],
        systems=["synth-random", "synth-brute"],
        difficulty_systems={2: ["synth-random"]},  # brute only on d1
        instances=2,
        seed=5,
        db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    records = storage.runs_to_records(experiment_id)
    storage.close()
    # d1: 2 instances x 2 systems; d2: 2 x 1 system.
    assert len(records) == 2 * 2 + 2 * 1
    d2_systems = {r.system_id for r in records if r.difficulty == 2}
    d1_systems = {r.system_id for r in records if r.difficulty == 1}
    assert d2_systems == {"synth-random"}
    assert d1_systems == {"synth-random", "synth-brute"}


def test_storage_roundtrip(tmp_db: str) -> None:
    storage = Storage(tmp_db)
    from vica.challenges.registry import build_challenge

    ch = build_challenge("csp-v0.1", "seed-1", 1)
    storage.save_challenge(ch, "now")
    record = RunRecord(
        experiment_id="exp-1",
        challenge_id=ch.id,
        challenge_type=ch.type,
        generator_version=ch.generator_version,
        difficulty=ch.difficulty,
        seed=ch.seed,
        system_id="random",
        candidate={"A0": 1},
        valid=True,
        score=1.0,
        solve_wall_time_ms=1.5,
        verify_time_us=20,
        error_code=None,
        metadata={"strategy": "uniform-random", "attempts": 3},
    )
    storage.save_run(record, "now")
    loaded = storage.runs_to_records("exp-1")
    assert len(loaded) == 1
    assert loaded[0].candidate == {"A0": 1}
    assert loaded[0].valid is True
    assert loaded[0].metadata["attempts"] == 3
    storage.close()


def test_metrics_aggregation() -> None:
    from vica.challenges.registry import build_challenge

    ch = build_challenge("csp-v0.1", "seed-m", 1)
    base = dict(
        experiment_id="exp-1",
        challenge_id=ch.id,
        challenge_type=ch.type,
        generator_version=ch.generator_version,
        difficulty=ch.difficulty,
        seed=ch.seed,
        candidate=None,
        solve_wall_time_ms=100.0,
        verify_time_us=50,
    )
    records = [
        RunRecord(**base, system_id="sys-a", valid=True, score=1.0,
                 metadata={"attempts": 10, "estimated_cost_usd": 0.0}),
        RunRecord(**base, system_id="sys-a", valid=False, score=0.0,
                 metadata={"attempts": 20, "estimated_cost_usd": 0.0}),
        RunRecord(**base, system_id="sys-a", valid=True, score=1.0,
                 metadata={"attempts": 5, "estimated_cost_usd": 0.01}),
    ]
    cells = aggregate(records)
    m = cells[("sys-a", 1)]
    assert m.instances == 3
    assert m.valid == 2
    assert m.success_rate == pytest.approx(2 / 3)
    assert m.mean_solve_ms == pytest.approx(100.0)
    assert m.p50_solve_ms == pytest.approx(100.0)
    assert m.mean_verify_us == pytest.approx(50.0)
    assert m.total_cost_usd == pytest.approx(0.01)
    assert m.cost_per_valid_solution == pytest.approx(0.005)
    assert m.valid_solutions_per_dollar == pytest.approx(200.0)
    assert m.mean_attempts == pytest.approx((10 + 20 + 5) / 3)


def test_leaderboard_rows(tmp_db: str) -> None:
    experiment_id = run_benchmark(
        challenge_type="csp-v0.1",
        difficulties=[1],
        systems=["random"],
        instances=4,
        seed=9,
        db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    records = storage.runs_to_records(experiment_id)
    storage.close()
    rows = leaderboard_rows(records)
    assert len(rows) == 1
    assert rows[0]["system_id"] == "random"
    assert rows[0]["instances"] == 4


def test_csv_export(tmp_db: str, tmp_path) -> None:
    experiment_id = run_benchmark(
        challenge_type="csp-v0.1",
        difficulties=[1],
        systems=["random"],
        instances=2,
        seed=3,
        db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    records = storage.runs_to_records(experiment_id)
    storage.close()

    out = tmp_path / "runs.csv"
    with out.open("w", newline="") as fh:
        write_runs_csv(records, fh)
    content = out.read_text()
    assert "challenge_id" in content
    assert content.count("\n") == 3  # header + 2 runs

    out2 = tmp_path / "metrics.csv"
    with out2.open("w", newline="") as fh:
        write_metrics_csv(records, fh)
    content2 = out2.read_text()
    assert "system_id" in content2
    assert "success_rate" in content2


def test_unknown_challenge_type_raises(tmp_db: str) -> None:
    with pytest.raises(ValueError):
        run_benchmark(
            challenge_type="nope-v1",
            difficulties=[1],
            systems=["random"],
            instances=1,
            seed=1,
            db_path=tmp_db,
        )


def test_unknown_system_raises(tmp_db: str) -> None:
    with pytest.raises(ValueError):
        run_benchmark(
            challenge_type="csp-v0.1",
            difficulties=[1],
            systems=["nope"],
            instances=1,
            seed=1,
            db_path=tmp_db,
        )


def test_synth_runner_produces_records(tmp_db: str) -> None:
    """SYNTH-v0.1 end-to-end through the runner + verifier + storage."""
    experiment_id = run_benchmark(
        challenge_type="synth-v0.1",
        difficulties=[1, 2],
        systems=["synth-random", "synth-brute"],
        instances=3,
        seed=11,
        db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    records = storage.runs_to_records(experiment_id)
    storage.close()
    assert len(records) == 2 * 2 * 3  # difficulties * systems * instances
    for r in records:
        assert r.challenge_type == "synth-v0.1"
        assert r.experiment_id == experiment_id
        assert r.verify_time_us >= 0
        assert isinstance(r.valid, bool)
        assert r.system_id in {"synth-random", "synth-brute"}
    # brute-force must solve at least one d=1 instance (its strong regime).
    d1_brute_valid = [
        r for r in records
        if r.difficulty == 1 and r.system_id == "synth-brute" and r.valid
    ]
    assert len(d1_brute_valid) >= 1