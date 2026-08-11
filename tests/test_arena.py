"""Tests for the arena runner, storage, metrics, and export."""

from __future__ import annotations

import pytest

from vica.arena.export import write_metrics_csv, write_runs_csv
from vica.arena.leaderboard import format_leaderboard, leaderboard_rows
from vica.arena.metrics import aggregate
from vica.arena.runner import run_benchmark
from vica.protocol.models import RunRecord, SolveOutput
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


class _NoCandidateSystem:
    """Fake system for SPEC 7.1/7.2 error-semantics mapping tests."""

    system_id = "fake-no-candidate"
    supported_challenge_types: frozenset[str] = frozenset({"csp-v0.1"})

    def __init__(self, status: str) -> None:
        self._status = status

    def solve(self, challenge: dict) -> SolveOutput:
        return SolveOutput(candidate=None, metadata={"strategy": "fake", "status": self._status})

    def config(self) -> dict:
        return {"strategy": "fake", "status": self._status}


@pytest.mark.parametrize(
    "status,expected_code",
    [
        ("timeout", "TIMEOUT"),
        ("provider_error", "INTERNAL_ERROR"),
        ("transport_error", "INTERNAL_ERROR"),
        ("parse_error", "INVALID_SOLUTION"),
        ("no_candidate", "INVALID_SOLUTION"),
    ],
)
def test_runner_maps_no_candidate_status(
    tmp_db: str, status: str, expected_code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC 7.1/7.2: timeouts and provider failures never count as wrong answers."""
    import vica.arena.runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "SYSTEM_FACTORIES",
        {"fake": lambda: _NoCandidateSystem(status)},
    )
    experiment_id = run_benchmark(
        challenge_type="csp-v0.1",
        difficulties=[1],
        systems=["fake"],
        instances=1,
        seed=3,
        db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    records = storage.runs_to_records(experiment_id)
    storage.close()
    assert len(records) == 1
    assert records[0].valid is False
    assert records[0].error_code == expected_code


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


def test_unknown_cost_is_na_not_zero() -> None:
    """A cost that is absent/None is UNKNOWN, never silently 0.

    SPEC "Cost semantics": none of the cost-derived metrics may be reported as
    0 when the cost is unknown — they must be N/A (None). A genuine known-zero
    total cost must also not yield a bogus SPD (division by zero is undefined).
    """
    from vica.challenges.registry import build_challenge

    ch = build_challenge("csp-v0.1", "cost-seed", 1)
    base = dict(
        experiment_id="exp-cost",
        challenge_id=ch.id,
        challenge_type=ch.type,
        generator_version=ch.generator_version,
        difficulty=ch.difficulty,
        seed=ch.seed,
        candidate=None,
        solve_wall_time_ms=100.0,
        verify_time_us=50,
    )
    # No 'estimated_cost_usd' key at all => UNKNOWN cost.
    unknown = RunRecord(
        **base, system_id="sys-unknown", valid=True, score=1.0, metadata={"attempts": 1}
    )
    uk = aggregate([unknown])[("sys-unknown", 1)]
    assert uk.cost_known is False
    assert uk.total_cost_usd is None
    assert uk.mean_cost_per_instance is None
    assert uk.cost_per_valid_solution is None
    assert uk.valid_solutions_per_dollar is None  # SPD must be N/A, not computed

    # Genuine known-zero total => SPD is undefined, reported as None, not inf.
    zero = RunRecord(
        **base,
        system_id="sys-zero",
        valid=True,
        score=1.0,
        metadata={"attempts": 1, "estimated_cost_usd": 0.0},
    )
    zc = aggregate([zero])[("sys-zero", 1)]
    assert zc.cost_known is True
    assert zc.total_cost_usd == pytest.approx(0.0)
    assert zc.valid_solutions_per_dollar is None


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


def test_leaderboard_renders_unknown_cost_as_na() -> None:
    """UNKNOWN cost must render as N/A in the text leaderboard, not crash."""
    from vica.challenges.registry import build_challenge
    from vica.protocol.models import RunRecord

    ch = build_challenge("synth-v0.1", "lb-na", 1)
    base = dict(
        experiment_id="e",
        challenge_id=ch.id,
        challenge_type=ch.type,
        generator_version=ch.generator_version,
        difficulty=ch.difficulty,
        seed=ch.seed,
        candidate=None,
        solve_wall_time_ms=10.0,
        verify_time_us=5,
    )
    # No estimated_cost_usd key => UNKNOWN cost.
    r = RunRecord(**base, system_id="sys", valid=True, score=1.0, metadata={"attempts": 1})
    rows = leaderboard_rows([r])
    assert rows[0]["total_cost_usd"] is None
    rendered = format_leaderboard(rows)
    assert "N/A" in rendered


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


def test_system_config_is_experiment_scoped(tmp_db: str) -> None:
    """System configs must be per-experiment snapshots, never overwritten."""
    storage = Storage(tmp_db)
    storage.save_system_config(
        "exp-a", "llm", "llm", {"model": "model-a", "provider": "openai-compatible"}
    )
    storage.save_system_config(
        "exp-b", "llm", "llm", {"model": "model-b", "provider": "openai-compatible"}
    )
    a = {c["system_id"]: c["config"] for c in storage.get_experiment_systems("exp-a")}
    b = {c["system_id"]: c["config"] for c in storage.get_experiment_systems("exp-b")}
    assert a["llm"]["model"] == "model-a"
    assert b["llm"]["model"] == "model-b"
    # Same system_id across two experiments must coexist without clobbering.
    assert a["llm"] != b["llm"]
    storage.close()


def test_runner_persists_experiment_scoped_configs(
    tmp_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner stores each experiment's own resolved config snapshot."""
    import vica.arena.runner as runner_mod

    class _Fake:
        system_id = "fake"
        supported_challenge_types: frozenset[str] = frozenset({"csp-v0.1"})

        def __init__(self, name: str) -> None:
            self._name = name

        def solve(self, challenge: dict) -> SolveOutput:
            return SolveOutput(candidate={"A0": 1}, metadata={"strategy": "fake"})

        def config(self) -> dict:
            return {"system_name": self._name}

    state = {"name": "A"}
    monkeypatch.setattr(
        runner_mod,
        "SYSTEM_FACTORIES",
        {"fake": lambda: _Fake(state["name"])},
    )
    exp_a = run_benchmark(
        challenge_type="csp-v0.1", difficulties=[1], systems=["fake"],
        instances=1, seed=1, db_path=tmp_db,
    )
    state["name"] = "B"
    exp_b = run_benchmark(
        challenge_type="csp-v0.1", difficulties=[1], systems=["fake"],
        instances=1, seed=2, db_path=tmp_db,
    )
    storage = Storage(tmp_db)
    cfg_a = {c["system_id"]: c["config"] for c in storage.get_experiment_systems(exp_a)}
    cfg_b = {c["system_id"]: c["config"] for c in storage.get_experiment_systems(exp_b)}
    storage.close()
    assert cfg_a["fake"]["system_name"] == "A"
    assert cfg_b["fake"]["system_name"] == "B"
    assert cfg_a != cfg_b


def test_real_v0_schema_migrates_and_preserves_runs(tmp_db: str) -> None:
    """The REAL legacy v0.1 schema (no env_json, no experiment_systems) opens,
    upgrades in place, and keeps historical experiments/runs working.

    The initial v0.1 release (origin/main ee61542) created:

        experiments (id, created_at, config_json, git_commit, vica_version)

    and had no ``experiment_systems`` table. A migration must add
    ``experiments.env_json``, create ``experiment_systems``, and leave every
    historical row untouched — and new writes must succeed afterwards.
    """
    import sqlite3

    from vica.challenges.registry import build_challenge

    # Reproduce the real legacy schema exactly (PRAGMA user_version = 0).
    conn = sqlite3.connect(tmp_db)
    conn.executescript(
        """
        CREATE TABLE experiments (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            config_json TEXT NOT NULL,
            git_commit TEXT,
            vica_version TEXT
        );
        CREATE TABLE challenges (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, generator_version TEXT NOT NULL,
            seed TEXT NOT NULL, difficulty INTEGER NOT NULL, payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE systems (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, config_json TEXT NOT NULL
        );
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL, challenge_id TEXT NOT NULL,
            challenge_type TEXT NOT NULL, generator_version TEXT NOT NULL,
            difficulty INTEGER NOT NULL, seed TEXT NOT NULL, system_id TEXT NOT NULL,
            candidate_json TEXT NOT NULL, valid INTEGER NOT NULL, score REAL NOT NULL,
            solve_wall_time_ms REAL NOT NULL, verify_time_us INTEGER NOT NULL,
            error_code TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX idx_runs_experiment ON runs(experiment_id);
        """
    )
    ch = build_challenge("csp-v0.1", "legacy-seed", 1)
    conn.execute(
        "INSERT INTO experiments (id, created_at, config_json, git_commit, vica_version) "
        "VALUES ('exp-legacy','now','{}','abc123','0.1.0')"
    )
    conn.execute(
        "INSERT INTO runs (experiment_id, challenge_id, challenge_type, generator_version, "
        "difficulty, seed, system_id, candidate_json, valid, score, solve_wall_time_ms, "
        "verify_time_us, error_code, metadata_json, created_at) "
        "VALUES ('exp-legacy',?,?,?,?,?,?,?,?,?,?,?,?,?,'now')",
        (
            ch.id, ch.type, ch.generator_version, ch.difficulty, ch.seed,
            "random", "{}", 1, 1.0, 1.5, 20, None, "{}",
        ),
    )
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 0
    conn.commit()
    conn.close()

    # Opening with the current Storage migrates the real legacy DB.
    import vica.storage.db as dbmod

    storage = Storage(tmp_db)
    assert storage.conn.execute("PRAGMA user_version").fetchone()[0] == dbmod._SCHEMA_VERSION
    # env_json column exists on the migrated experiments table.
    experiment_columns = {
        row[1] for row in storage.conn.execute("PRAGMA table_info(experiments)")
    }
    assert "env_json" in experiment_columns
    # experiment_systems exists with the current shape.
    systems_columns = {
        row[1] for row in storage.conn.execute("PRAGMA table_info(experiment_systems)")
    }
    assert {"experiment_id", "system_id", "type", "config_json"} <= systems_columns
    # Historical experiment and runs are preserved unchanged.
    legacy = storage.get_experiment("exp-legacy")
    assert legacy is not None
    assert legacy["git_commit"] == "abc123"
    assert legacy["vica_version"] == "0.1.0"
    assert "env_json" in legacy
    runs = storage.runs_to_records("exp-legacy")
    assert len(runs) == 1
    assert runs[0].system_id == "random"
    assert runs[0].valid is True
    # New writes after the migration succeed (no "no column named env_json").
    storage.save_experiment(
        experiment_id="exp-new",
        config={"challenge_type": "csp-v0.1"},
        created_at="now",
        git_commit=None,
        vica_version="0.1.0",
        environment={"os": "test"},
    )
    assert storage.get_experiment("exp-new")["env_json"] is not None
    storage.close()

    # Reopening is idempotent: no error, no duplicate columns.
    storage2 = Storage(tmp_db)
    assert storage2.conn.execute("PRAGMA user_version").fetchone()[0] == dbmod._SCHEMA_VERSION
    assert storage2.get_experiment("exp-legacy") is not None
    storage2.close()


def test_incompatible_challenge_system_pairing_fails_fast(tmp_db: str) -> None:
    """z3 + synth is a config error: ValueError before any run is written."""
    from pathlib import Path

    assert not Path(tmp_db).exists()
    with pytest.raises(ValueError, match="does not support challenge"):
        run_benchmark(
            challenge_type="synth-v0.1",
            difficulties=[1],
            systems=["z3"],
            instances=1,
            seed=1,
            db_path=tmp_db,
        )
    # fail-fast happens before the DB is created: no run records, no storage.
    assert not Path(tmp_db).exists()


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