"""REPO-v0.1 generator — workspace + reference patch + hidden material.

Secret-bound like SYNTH-v0.1 (docs/SPEC.md "Verifier material"): the reference
(fixed) source and the hidden test cases are derivable only from the verifier
secret, never from the public ``(seed, difficulty)``. The public workspace
(buggy source) and the public test *inputs* are the only solver-visible
material; the expected outputs of the public tests equal the buggy output
(a NoOp patch passes them — the honest hint), while the hidden tests are the
discriminating negative control (a NoOp patch fails them).

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
from vica.repo.templates import Template, classify_hidden, classify_public, template_for
from vica.repo.workspace import manifest_hash, materialize_workspace, validate_manifest

TYPE_NAME = "repo-v0.1"
GENERATOR_VERSION = "0.1.0"
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
    """Deterministic PRNG for solver-visible public material (test inputs).

    Keyed only by the public (seed, difficulty). It never samples the fixed
    reference, so knowing this RNG cannot recover the reference patch or the
    hidden tests.
    """
    return random.Random(f"{TYPE_NAME}:{GENERATOR_VERSION}:public:{seed}:{difficulty}")


def _secret_rng(verifier_secret: str, tag: str, seed: str, difficulty: int) -> random.Random:
    """Deterministic PRNG keyed by the verifier secret with a domain tag.

    ``seed = HMAC-SHA256(verifier_secret, type:version:tag:seed:difficulty)``.
    The ``hidden`` tag domain-separates the hidden stream from any other
    secret-bound stream. Knowing only the public (seed, difficulty) — without
    the secret — cannot reconstruct this stream.
    """
    tag_bytes = f"{TYPE_NAME}:{GENERATOR_VERSION}:{tag}:{seed}:{difficulty}".encode()
    digest = hmac.new(verifier_secret.encode("utf-8"), tag_bytes, hashlib.sha256).hexdigest()
    return random.Random(digest)


def _hidden_rng(verifier_secret: str, seed: str, difficulty: int) -> random.Random:
    """RNG for hidden test cases (verifier-only)."""
    return _secret_rng(verifier_secret, "hidden", seed, difficulty)


# ------------------------------------------------------------------ workspace

def _render_literal(value: Any) -> str:
    return repr(value)


def _public_test_file(template: Template, public_cases: list[dict[str, Any]]) -> str:
    """Render the solver-visible pytest file encoding the public cases."""
    lines = [
        f'"""Public tests for the {template.name} task (REPO-v0.1)."""',
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


def _task_text(template: Template) -> str:
    return (
        f"# {template.name}\n\n"
        f"task_kind: {template.task_kind}\n\n"
        f"{template.task}\n\n"
        "Modify `solution.py` and keep the `solve` interface. Public tests are "
        "in `tests/test_public.py`. Do not modify anything under `tests/`.\n"
    )


def _workspace_files(
    template: Template, public_cases: list[dict[str, Any]]
) -> dict[str, str]:
    return {
        SOLUTION_PATH: template.buggy,
        TASK_PATH: _task_text(template),
        PUBLIC_TEST_PATH: _public_test_file(template, public_cases),
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

def _make_reference_patch(template: Template, payload: dict[str, Any]) -> str:
    """Build the git unified diff that turns the buggy workspace into the fixed one.

    Materializes the authoritative workspace in a temp dir, commits it, writes
    the fixed ``solution.py`` in place, and runs ``git diff``. The result is a
    patch that ``git apply`` (and therefore :func:`vica.repo.patch.apply_patch`)
    can replay exactly. Only ``solution.py`` is touched.
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
        (ws / SOLUTION_PATH).write_text(template.fixed)
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
    """Solver-visible payload for (seed, difficulty).

    Contains the workspace (buggy source + public test inputs + task), the
    structural constraints, and the public test input vectors. It never
    contains the fixed source, the reference patch, or the hidden tests —
    those require the verifier secret (authoritative path:
    ``generate_with_solution`` / ``family.generate_with_solution``).
    """
    template = template_for(seed)
    preset = DIFFICULTY_PRESETS[difficulty]
    public_cases = classify_public(
        template, _public_rng(seed, difficulty), count=preset.public_count
    )
    files = _workspace_files(template, public_cases)
    manifest = _manifest_from_files(files)
    return {
        "task_kind": template.task_kind,
        "language": "python",
        "task": _task_text(template),
        "template": template.name,
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
        "public_test_inputs": [{"args": list(c["args"])} for c in public_cases],
    }


def generate(seed: str, difficulty: int) -> dict[str, Any]:
    """Public payload for (seed, difficulty). See :func:`_public_payload`."""
    _check_difficulty(difficulty)
    return dict(_public_payload(seed, difficulty))


@lru_cache(maxsize=4096)
def _payload_with_solution(
    seed: str, difficulty: int, verifier_secret: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authoritative assembly: full solver payload + verifier-only solution."""
    template = template_for(seed)
    preset = DIFFICULTY_PRESETS[difficulty]
    payload = dict(_public_payload(seed, difficulty))
    public_cases = classify_public(
        template, _public_rng(seed, difficulty), count=preset.public_count
    )
    payload["public_tests"] = [
        {"args": list(c["args"]), "expected": c["expected"]} for c in public_cases
    ]
    hidden_cases = classify_hidden(
        template, _hidden_rng(verifier_secret, seed, difficulty), count=preset.hidden_count
    )
    solution = {
        "reference_patch": _make_reference_patch(template, payload),
        "fixed_source": template.fixed,
        "hidden_tests": [
            {"args": list(c["args"]), "expected": c["expected"]} for c in hidden_cases
        ],
    }
    return payload, solution


def generate_with_solution(
    seed: str, difficulty: int, verifier_secret: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authoritative generation (see :func:`_payload_with_solution`)."""
    _check_difficulty(difficulty)
    return _payload_with_solution(seed, difficulty, verifier_secret)


def hidden_tests_for(
    seed: str, difficulty: int, verifier_secret: str
) -> list[dict[str, Any]]:
    """Hidden test cases (args, expected) — for tests/calibration only.

    Requires the verifier *secret*; a solver holding only the public challenge
    cannot call this to obtain hidden material.
    """
    _check_difficulty(difficulty)
    template = template_for(seed)
    preset = DIFFICULTY_PRESETS[difficulty]
    cases = classify_hidden(
        template, _hidden_rng(verifier_secret, seed, difficulty), count=preset.hidden_count
    )
    return [{"args": list(c["args"]), "expected": c["expected"]} for c in cases]


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