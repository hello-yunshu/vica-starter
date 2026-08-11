"""SQLite storage for challenges, systems, experiments, and runs.

Schema follows docs/SPEC.md section 12.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from vica.protocol.models import Challenge, ErrorCode, RunRecord
from vica.protocol.serialization import canonical_json_bytes

_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    config_json TEXT NOT NULL,
    env_json TEXT,
    git_commit TEXT,
    vica_version TEXT
);
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    seed TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS systems (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_systems (
    experiment_id TEXT NOT NULL,
    system_id TEXT NOT NULL,
    type TEXT NOT NULL,
    config_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, system_id)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    challenge_id TEXT NOT NULL,
    challenge_type TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    seed TEXT NOT NULL,
    system_id TEXT NOT NULL,
    candidate_json TEXT NOT NULL,
    valid INTEGER NOT NULL,
    score REAL NOT NULL,
    solve_wall_time_ms REAL NOT NULL,
    verify_time_us INTEGER NOT NULL,
    error_code TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs(experiment_id);
CREATE INDEX IF NOT EXISTS idx_runs_system ON runs(system_id, difficulty);
"""


class Storage:
    """Thin SQLite wrapper. One connection per process lifetime is enough for MVP."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        """Idempotent schema migration via ``PRAGMA user_version``.

        Legacy v0.1 databases have no ``experiment_systems`` table (system
        configs lived in the global ``systems`` table and were overwritten by
        later experiments). Opening any database — fresh or legacy — converges
        on the current schema: all DDL is ``CREATE TABLE IF NOT EXISTS``, and
        ``user_version`` is set to the current schema version. Historical runs
        are never touched.
        """
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        self.conn.executescript(_SCHEMA)
        if version != _SCHEMA_VERSION:
            self.conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ writes

    def save_experiment(
        self,
        experiment_id: str,
        config: dict,
        created_at: str,
        git_commit: str | None,
        vica_version: str,
        environment: dict | None = None,
    ) -> None:
        # Canonical JSON rejects NaN/Infinity, keeping storage consistent with
        # the protocol (SPEC "Data interchange").
        self.conn.execute(
            "INSERT OR REPLACE INTO experiments "
            "(id, created_at, config_json, env_json, git_commit, vica_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                experiment_id,
                created_at,
                canonical_json_bytes(config).decode("utf-8"),
                canonical_json_bytes(environment or {}).decode("utf-8"),
                git_commit,
                vica_version,
            ),
        )
        self.conn.commit()

    def save_challenge(self, challenge: Challenge, created_at: str) -> None:
        payload_json = canonical_json_bytes(challenge.payload).decode("utf-8")
        self.conn.execute(
            "INSERT OR REPLACE INTO challenges "
            "(id, type, generator_version, seed, difficulty, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                challenge.id,
                challenge.type,
                challenge.generator_version,
                challenge.seed,
                challenge.difficulty,
                payload_json,
                created_at,
            ),
        )
        self.conn.commit()

    def save_system(self, system_id: str, type_: str, config: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO systems (id, type, config_json) VALUES (?, ?, ?)",
            (system_id, type_, canonical_json_bytes(config).decode("utf-8")),
        )
        self.conn.commit()

    def save_system_config(
        self, experiment_id: str, system_id: str, type_: str, config: dict
    ) -> None:
        """Persist one experiment's resolved system-config snapshot.

        Configs are experiment-scoped (``experiment_systems``): a later
        experiment with a different config never overwrites an earlier one,
        so historical runs stay reproducible (SPEC "Reproducibility"). Only
        non-secret config fields are recorded; credentials must not be part of
        a system's ``config()``.
        """
        self.conn.execute(
            "INSERT OR REPLACE INTO experiment_systems "
            "(experiment_id, system_id, type, config_json) VALUES (?, ?, ?, ?)",
            (
                experiment_id,
                system_id,
                type_,
                canonical_json_bytes(config).decode("utf-8"),
            ),
        )
        self.conn.commit()

    def save_run(self, record: RunRecord, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO runs ("
            "experiment_id, challenge_id, challenge_type, generator_version, difficulty, "
            "seed, system_id, candidate_json, valid, score, solve_wall_time_ms, "
            "verify_time_us, error_code, metadata_json, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.experiment_id,
                record.challenge_id,
                record.challenge_type,
                record.generator_version,
                record.difficulty,
                record.seed,
                record.system_id,
                canonical_json_bytes(record.candidate).decode("utf-8"),
                1 if record.valid else 0,
                record.score,
                record.solve_wall_time_ms,
                record.verify_time_us,
                record.error_code.value if record.error_code else None,
                canonical_json_bytes(record.metadata).decode("utf-8"),
                created_at,
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------------- reads

    def get_experiment(self, experiment_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_experiment_systems(self, experiment_id: str) -> list[dict]:
        """Resolved system-config snapshots for one experiment.

        Returns list of ``{"system_id", "type", "config"}`` in insertion
        order for the given experiment.
        """
        rows = self.conn.execute(
            "SELECT system_id, type, config_json FROM experiment_systems "
            "WHERE experiment_id = ? ORDER BY system_id",
            (experiment_id,),
        ).fetchall()
        return [
            {
                "system_id": row["system_id"],
                "type": row["type"],
                "config": json.loads(row["config_json"]),
            }
            for row in rows
        ]

    def iter_runs(self, experiment_id: str):
        cur = self.conn.execute(
            "SELECT * FROM runs WHERE experiment_id = ? ORDER BY id", (experiment_id,)
        )
        return cur.fetchall()

    def runs_to_records(self, experiment_id: str) -> list[RunRecord]:
        records: list[RunRecord] = []
        for row in self.iter_runs(experiment_id):
            records.append(
                RunRecord(
                    experiment_id=row["experiment_id"],
                    challenge_id=row["challenge_id"],
                    challenge_type=row["challenge_type"],
                    generator_version=row["generator_version"],
                    difficulty=row["difficulty"],
                    seed=row["seed"],
                    system_id=row["system_id"],
                    candidate=json.loads(row["candidate_json"]),
                    valid=bool(row["valid"]),
                    score=row["score"],
                    solve_wall_time_ms=row["solve_wall_time_ms"],
                    verify_time_us=row["verify_time_us"],
                    error_code=ErrorCode(row["error_code"]) if row["error_code"] else None,
                    metadata=json.loads(row["metadata_json"]),
                )
            )
        return records


__all__ = ["Storage"]