"""REPO-v0.1 generator — secret-bound instances + workspace + reference patch.

Generator semantics 0.3.0 (v1.0.2 semantic-oracle verifier):

- **Instances are secret-bound.** The concrete source instance (identifiers,
  helper-vs-inline structure, constants, data shapes, code organization) is
  assembled from a domain-separated RNG derived from the verifier secret. The
  public ``(seed, difficulty)`` alone selects the *template* and the public
  test-input stream; it never determines the instance, the fixed source, or
  the reference patch (docs/SPEC.md "Verifier material").
- **``generate()`` is public-only.** It returns template metadata without the
  workspace: without the verifier secret there is no way to assemble the
  solver-visible workspace or the reference material. A solver-facing call
  cannot retrieve an exact reference patch (must verify:
  ``generate_with_solution(..., verifier_secret)``).
- **The authoritative expected values come from an independent oracle.** Each
  template exposes a pure ``input -> expected`` function of its semantics
  (``SourceInstance.oracle``). Public/hidden classification and the hidden
  tests are computed against the oracle, not by executing a recoverable fixed
  source. Correctness is pinned to the public spec; an attacker recovering
  ``fixed`` by enumerating the open-source builder gains no advantage, because
  fixing the workspace to match the public oracle spec is the honest task.
  The reference patch (git diff buggy -> fixed) remains a calibration/positive
  control generated only in the authoritative path.
- **The authoritative path is ``generate_with_solution``.** It builds the
  instance, renders the buggy workspace, classifies public cases (inputs where
  buggy == oracle — a NoOp patch passes them), classifies hidden cases (inputs
  where buggy != oracle — a NoOp patch fails them), computes the reference
  patch, and binds everything to the secret. Different seeds genuinely change
  the solver-visible source instance, so patches generally differ across seeds,
  not just the hidden inputs.
- **Historical 0.1.0 / 0.2.0 are withdrawn.** 0.1.0 exposed static
  buggy/fixed template sources and verified in a shared interpreter; 0.2.0
  added process-separated verification but its expected values still derived
  from a recoverable fixed source. 0.3.0 denies verification of both
  (family-level gate).

The workspace is a small, self-contained Python repo:

    solution.py            # the buggy ``solve`` the agent must fix
    tests/test_public.py   # public test cases (honest hint, immutable)
    task.md                # the task description

The identity is the workspace manifest hash (see :mod:`vica.repo.workspace`).
The reference patch is the git unified diff that turns ``solution.py`` from the
buggy source into the fixed source; it is never shipped to the solver.
"""

from __future__ import annotations

import hashlib
import hmac
import random
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from vica.repo.patch import MAX_CHANGED_FILES, MAX_PATCH_BYTES
from vica.repo.templates import (
    SourceInstance,
    build_source_instance,
    classify_hidden,
    classify_public,
    template_for,
)
from vica.repo.workspace import manifest_hash, materialize_workspace, validate_manifest

TYPE_NAME = "repo-v0.1"
# 0.3.0 = semantic-oracle verifier (v1.0.2): expected values come from an
# independent per-template oracle, not from a recoverable fixed source.
# Historical 0.1.0 (static templates + shared-interpreter verification) and
# 0.2.0 (process-separated but recoverable fixed-source expected values) are
# withdrawn and denied by the family version gate.
GENERATOR_VERSION = "0.3.0"
VERIFIER_SECRET_KEY = "_verifier_secret"
MAX_DIFFICULTY = 3

# Relative paths that make up every REPO-v0.1 workspace.
SOLUTION_PATH = "solution.py"
TASK_PATH = "task.md"
PUBLIC_TEST_PATH = "tests/test_public.py"


@dataclass(frozen=True)
class Preset:
    """Difficulty preset: how many public / hidden cases an instance carries."""

    public_count: int
    hidden_count: int


DIFFICULTY_PRESETS: dict[int, Preset] = {
    1: Preset(public_count=4, hidden_count=6),
    2: Preset(public_count=4, hidden_count=10),
    3: Preset(public_count=4, hidden_count=14),
}


# ------------------------------------------------------------------ RNG streams

def _public_rng(seed: str, difficulty: int) -> random.Random:
    """Deterministic PRNG for solver-visible public test inputs.

    Keyed only by the public (seed, difficulty). It never samples the fixed
    reference, so knowing this RNG cannot recover the reference patch or the
    hidden tests.
    """
    return random.Random(f"{TYPE_NAME}:{GENERATOR_VERSION}:public:{seed}:{difficulty}")


def _secret_rng(verifier_secret: str, tag: str, seed: str, difficulty: int) -> random.Random:
    """Deterministic PRNG keyed by the verifier secret with a domain tag.

    ``seed = HMAC-SHA256(verifier_secret, type:version:tag:seed:difficulty)``.
    The ``instance`` and ``hidden`` tags domain-separate the two streams: even
    with the same secret, instance material and hidden-test material never
    share an RNG stream. Knowing only the public (seed, difficulty) — without
    the secret — cannot reconstruct either stream.
    """
    tag_bytes = f"{TYPE_NAME}:{GENERATOR_VERSION}:{tag}:{seed}:{difficulty}".encode()
    digest = hmac.new(verifier_secret.encode("utf-8"), tag_bytes, hashlib.sha256).hexdigest()
    return random.Random(digest)


def _instance_rng(verifier_secret: str, seed: str, difficulty: int) -> random.Random:
    """RNG for the concrete source instance (verifier-only).

    The instance determines the workspace source text and the fixed reference
    source, so this stream is what keeps the reference patch secret-bound.
    """
    return _secret_rng(verifier_secret, "instance", seed, difficulty)


def _hidden_rng(verifier_secret: str, seed: str, difficulty: int) -> random.Random:
    """RNG for hidden test inputs (verifier-only).

    Domain-separated from the instance stream via the ``hidden`` tag.
    """
    return _secret_rng(verifier_secret, "hidden", seed, difficulty)


def _instance(verifier_secret: str, seed: str, difficulty: int) -> SourceInstance:
    """The secret-bound SourceInstance for (secret, seed, difficulty)."""
    return build_source_instance(
        template_for(seed),
        _instance_rng(verifier_secret, seed, difficulty),
    )


# ------------------------------------------------------------------ workspace

def _render_literal(value: Any) -> str:
    return repr(value)


def _public_test_file(instance: SourceInstance, public_cases: list[dict[str, Any]]) -> str:
    """Render the solver-visible pytest file encoding the public cases."""
    lines = [
        f'"""Public tests for the {instance.template} task (REPO-v0.1)."""',
        "from __future__ import annotations",
        "",
        "import solution",
        "",
        "",
        "def test_public_cases() -> None:",
        "    cases = [",
    ]
    for case in public_cases:
        args = ", ".join(_render_literal(a) for a in case["args"])
        lines.append(f"        ({args}, {_render_literal(case['expected'])}),")
    lines += [
        "    ]",
        "    for i, (args, expected) in enumerate(cases):",
        "        got = solution.solve(*args)",
        "        assert got == expected, "
        "f'case {i}: got {got!r}, expected {expected!r}'",
    ]
    return "\n".join(lines) + "\n"


def _task_text(instance: SourceInstance) -> str:
    return (
        f"# {instance.template}\n\n"
        f"task_kind: {instance.task_kind}\n\n"
        f"{instance.task}\n\n"
        "Modify `solution.py` and keep the `solve` interface. Public tests are "
        "in `tests/test_public.py`. Do not modify anything under `tests/`.\n"
    )


def _workspace_files(
    instance: SourceInstance, public_cases: list[dict[str, Any]]
) -> dict[str, str]:
    return {
        SOLUTION_PATH: instance.buggy,
        TASK_PATH: _task_text(instance),
        PUBLIC_TEST_PATH: _public_test_file(instance, public_cases),
    }


def _manifest_from_files(files: dict[str, str]) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(files):
        data = files[path].encode("utf-8")
        entries.append(
            {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "mode": "644"}
        )
    # validate_manifest enforces sorted POSIX paths / no duplicates / no traversal.
    return validate_manifest(entries)


def _materialize(payload: dict[str, Any], dest: str | Path) -> Path:
    files = {p: v.encode("utf-8") for p, v in payload["workspace_files"].items()}
    return materialize_workspace(payload["workspace_manifest"], files, dest)


# ------------------------------------------------------------------ reference patch

def _make_reference_patch(instance: SourceInstance, payload: dict[str, Any]) -> str:
    """Build the git unified diff that turns the buggy workspace into the fixed one.

    Materializes the authoritative workspace in a temp dir, commits it, writes
    the fixed ``solution.py`` in place, and runs ``git diff``. The result is a
    patch that ``git apply`` (and therefore :func:`vica.repo.patch.apply_patch`)
    can replay exactly. Only ``solution.py`` is touched. Computed exclusively
    in the authoritative path (``generate_with_solution``); no public API emits
    it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        _materialize(payload, ws)
        subprocess.run(["git", "init", "-q", str(ws)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(ws), "add", "-A"], check=True, capture_output=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(ws),
                "-c",
                "user.email=vica@invalid",
                "-c",
                "user.name=vica",
                "commit",
                "-q",
                "-m",
                "base",
            ],
            check=True,
            capture_output=True,
        )
        (ws / SOLUTION_PATH).write_text(instance.fixed)
        diff = subprocess.run(
            ["git", "-C", str(ws), "diff"], check=True, capture_output=True, text=True
        )
        return diff.stdout


# ------------------------------------------------------------------ generation

def _check_difficulty(difficulty: int) -> None:
    if difficulty not in DIFFICULTY_PRESETS:
        raise ValueError(
            f"unsupported difficulty {difficulty}; supported: {sorted(DIFFICULTY_PRESETS)}"
        )


@lru_cache(maxsize=4096)
def _public_payload(seed: str, difficulty: int) -> dict[str, Any]:
    """Public-generation part for (seed, difficulty) — metadata only.

    Contains no workspace and no reference material: without the verifier
    secret there is no way to assemble the solver-visible workspace or the
    expected outputs, because the concrete instance is secret-bound. The
    authoritative payload is ``generate_with_solution``.
    """
    template = template_for(seed)
    return {
        "task_kind": template.task_kind,
        "language": "python",
        "template": template.name,
        "public_part": True,
    }


@lru_cache(maxsize=4096)
def _authoritative(
    seed: str, difficulty: int, verifier_secret: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authoritative assembly: full solver payload + verifier-only solution.

    Deterministic for a fixed (secret, seed, difficulty); a different secret
    yields a different instance, hence a different workspace and reference
    patch. Used by ``generate_with_solution`` and by the family verifier's
    hidden-test regeneration (so verification always reproduces the exact
    material the challenge was built with).
    """
    preset = DIFFICULTY_PRESETS[difficulty]
    instance = _instance(verifier_secret, seed, difficulty)
    public_cases = classify_public(
        instance, _public_rng(seed, difficulty), count=preset.public_count
    )
    hidden_cases = classify_hidden(
        instance, _hidden_rng(verifier_secret, seed, difficulty), count=preset.hidden_count
    )
    files = _workspace_files(instance, public_cases)
    manifest = _manifest_from_files(files)
    payload = {
        "task_kind": instance.task_kind,
        "language": "python",
        "task": _task_text(instance),
        "template": instance.template,
        "constraints": {
            "allowed_paths": [SOLUTION_PATH],
            "forbidden_paths": ["private/", "tests/"],
            "protected_paths": ["private/", "tests/"],
            "max_changed_files": MAX_CHANGED_FILES,
            "max_patch_bytes": MAX_PATCH_BYTES,
        },
        "workspace_hash": manifest_hash(manifest),
        "workspace_manifest": manifest,
        "workspace_files": files,
        "public_tests": [
            {"args": list(c["args"]), "expected": c["expected"]} for c in public_cases
        ],
    }
    solution = {
        "reference_patch": _make_reference_patch(instance, payload),
        "fixed_source": instance.fixed,
        "hidden_tests": [
            {"args": list(c["args"]), "expected": c["expected"]} for c in hidden_cases
        ],
    }
    return payload, solution


def generate(seed: str, difficulty: int) -> dict[str, Any]:
    """Public-only generation: template metadata, no workspace / no reference.

    Without the verifier secret the concrete instance (and therefore the
    workspace source, expected outputs, and the reference patch) cannot be
    assembled. There is deliberately no secretless path that returns an exact
    reference patch.
    """
    _check_difficulty(difficulty)
    return dict(_public_payload(seed, difficulty))


def generate_with_solution(
    seed: str, difficulty: int, verifier_secret: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authoritative generation (see :func:`_authoritative`)."""
    _check_difficulty(difficulty)
    payload, solution = _authoritative(seed, difficulty, verifier_secret)
    return dict(payload), dict(solution)


def hidden_tests_for(
    seed: str, difficulty: int, verifier_secret: str
) -> list[dict[str, Any]]:
    """Hidden test cases (args, expected) — for tests/calibration only.

    Requires the verifier *secret*; a solver holding only the public challenge
    cannot call this to obtain hidden material. Regenerated deterministically
    from the same authoritative assembly the challenge was built with, so the
    family verifier reproduces the exact hidden vectors.
    """
    _check_difficulty(difficulty)
    return [dict(c) for c in _authoritative(seed, difficulty, verifier_secret)[1]["hidden_tests"]]


__all__ = [
    "DIFFICULTY_PRESETS",
    "GENERATOR_VERSION",
    "MAX_DIFFICULTY",
    "PUBLIC_TEST_PATH",
    "Preset",
    "SOLUTION_PATH",
    "TASK_PATH",
    "TYPE_NAME",
    "VERIFIER_SECRET_KEY",
    "generate",
    "generate_with_solution",
    "hidden_tests_for",
]