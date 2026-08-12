"""Task Pack — v0.4 (docs/REPRODUCIBILITY.md, docs/SPEC.md "Task Pack").

A Task Pack is the stable, versioned identity of a *benchmark instance set*:
the concrete tasks (their challenge ids, and for REPO their workspace hashes)
that an evaluation runs. It is what makes a benchmark result reproducible and
comparable across systems and runs:

- ``task_pack_id``      — stable logical family name (e.g. ``repo-v0.1-generated``
  for a dynamic REPO evaluation; only a truly frozen official core pack may use
  ``repo-v0.1-core``).
- ``task_pack_version`` — bumped whenever the task *semantics* change; a
  released task pack is never silently mutated.
- ``task_pack_hash``    — SHA-256 of the canonical serialization of the task
  definition (challenge ids + workspace hashes + generator identity). Two
  runs over the same task set always produce the same hash.

A Result Bundle records ``task_pack_id`` / ``task_pack_version`` /
``task_pack_hash``, and strict reverify binds the hash so a tampered result set
is detected even when valid/score happen to coincide (§50 / §59).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vica.protocol.serialization import stable_hash

# v1.0.1 (research-integrity hotfix): the REPO generator semantics changed
# (0.1.0 -> 0.2.0, expected-value process isolation). A dynamic REPO evaluation
# is therefore labelled ``repo-v0.1-generated`` (not ``core``) — only a truly
# frozen official core pack may claim ``repo-v0.1-core``, and none is
# established in this round. The ``<type>-core`` id is reserved for an actually
# frozen core; other families keep their own baseline id.
TASK_PACK_ID_BY_TYPE: dict[str, str] = {
    "repo-v0.1": "repo-v0.1-generated",
}
DEFAULT_TASK_PACK_ID = "benchmark-core"
# Maturity of the Task Pack format itself. Bump only on a breaking change to
# the task-set identity definition (not on a new task set). v1 -> v2: the
# REPO generator / verifier semantics changed, so a candidate's validity may
# differ; packs and results built under the old semantics must not be silently
# re-identified under the new ones.
TASK_PACK_VERSION = "2"


@dataclass(frozen=True)
class TaskPack:
    """Immutable identity of a benchmark instance set."""

    task_pack_id: str
    task_pack_version: str
    challenge_type: str
    generator_version: str
    seed: int
    difficulties: tuple[int, ...]
    instances_per_difficulty: int
    challenge_ids: tuple[str, ...]
    workspace_hashes: tuple[str, ...]
    task_pack_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_pack_id": self.task_pack_id,
            "task_pack_version": self.task_pack_version,
            "challenge_type": self.challenge_type,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "difficulties": list(self.difficulties),
            "instances_per_difficulty": self.instances_per_difficulty,
            "challenge_ids": list(self.challenge_ids),
            "workspace_hashes": list(self.workspace_hashes),
            "task_pack_hash": self.task_pack_hash,
        }


def _challenge_workspace_hash(challenge: dict[str, Any]) -> str | None:
    """The authoritative REPO workspace hash for a challenge, if any."""
    payload = challenge.get("payload")
    if not isinstance(payload, dict):
        return None
    value = payload.get("workspace_hash")
    return str(value) if isinstance(value, str) and value else None


def task_pack_definition(
    public_manifest: dict[str, Any], challenges: list[dict[str, Any]]
) -> dict[str, Any]:
    """The canonical, ordered definition of a task set (no hash field).

    Ordered by challenge id so the hash is independent of source iteration
    order without needing a separate sort. Includes the generator identity and
    the authoritative workspace hashes (REPO) so a changed task set — or a
    tampered challenge — changes the hash.
    """
    ordered = sorted(challenges, key=lambda c: str(c.get("id", "")))
    return {
        "challenge_type": public_manifest.get("challenge_type"),
        "generator_version": public_manifest.get("generator_version"),
        "seed": public_manifest.get("seed"),
        "difficulties": sorted(
            {int(c.get("difficulty", 0)) for c in ordered}
        ),
        "instances_per_difficulty": public_manifest.get("instances_per_difficulty"),
        "challenge_ids": [str(c.get("id", "")) for c in ordered],
        "workspace_hashes": [
            _challenge_workspace_hash(c) or "" for c in ordered
        ],
    }


def task_pack_hash(public_manifest: dict[str, Any], challenges: list[dict[str, Any]]) -> str:
    """Stable SHA-256 of the canonical task-set definition."""
    return stable_hash(task_pack_definition(public_manifest, challenges))


def task_pack_id_for(challenge_type: str) -> str:
    return TASK_PACK_ID_BY_TYPE.get(challenge_type, DEFAULT_TASK_PACK_ID)


def derive_task_pack(
    public_manifest: dict[str, Any], challenges: list[dict[str, Any]]
) -> TaskPack:
    """Build the authoritative Task Pack for an Evaluation Bundle."""
    challenge_type = str(public_manifest.get("challenge_type", ""))
    definition = task_pack_definition(public_manifest, challenges)
    ordered = sorted(challenges, key=lambda c: str(c.get("id", "")))
    return TaskPack(
        task_pack_id=task_pack_id_for(challenge_type),
        task_pack_version=TASK_PACK_VERSION,
        challenge_type=challenge_type,
        generator_version=str(public_manifest.get("generator_version", "")),
        seed=int(public_manifest.get("seed", 0)),
        difficulties=tuple(sorted({int(c.get("difficulty", 0)) for c in ordered})),
        instances_per_difficulty=int(public_manifest.get("instances_per_difficulty", 0)),
        challenge_ids=tuple(str(c.get("id", "")) for c in ordered),
        workspace_hashes=tuple(_challenge_workspace_hash(c) or "" for c in ordered),
        task_pack_hash=stable_hash(definition),
    )


__all__ = [
    "DEFAULT_TASK_PACK_ID",
    "TASK_PACK_VERSION",
    "TaskPack",
    "derive_task_pack",
    "task_pack_hash",
    "task_pack_id_for",
]