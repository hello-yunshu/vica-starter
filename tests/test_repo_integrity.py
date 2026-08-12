"""v1.0.1 REPO research-integrity tests (P0).

Covers the two P0 fixes plus generator semantics (§48-49 of the hotfix):

- process-separated candidate verification: frame inspection / monkeypatch /
  module probing cannot reach expected values; hidden expected and the
  verifier secret never reach the candidate process;
- static reference-source leakage: ``TEMPLATES[name].fixed`` no longer
  exists and no secretless public API yields a reference patch;
- generator 0.2.0 semantics: secret-bound instances, deterministic
  regeneration, seed-dependent source instances, wrong-secret rejection;
- candidate process failure classification (crash / non-serializable output
  -> PROCESS_FAILURE, never a test comparison or INTERNAL_ERROR).
"""

from __future__ import annotations

import hashlib
import json
import shlex
import sys
import tempfile
from pathlib import Path

import pytest

from vica.eval.bundle import prepare_evaluation
from vica.protocol.models import ErrorCode
from vica.repo.family import FAMILY
from vica.repo.generator import (
    GENERATOR_VERSION,
    TYPE_NAME,
    VERIFIER_SECRET_KEY,
    generate,
    generate_with_solution,
    hidden_tests_for,
)
from vica.repo.workspace import materialize_workspace
from vica.sandbox.runner import safe_child_environment

_SECRET = "repo-integrity-secret-01"


def _challenge_dict(payload: dict, seed: str, difficulty: int, secret: str) -> dict:
    return {
        "type": TYPE_NAME,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "difficulty": difficulty,
        "payload": payload,
        VERIFIER_SECRET_KEY: secret,
    }


def _materialized(payload: dict, tmp: Path) -> Path:
    return materialize_workspace(
        payload["workspace_manifest"],
        {k: v.encode("utf-8") for k, v in payload["workspace_files"].items()},
        tmp / "ws",
    )


def _payload_with_solution(payload: dict, source: str) -> dict:
    """A payload whose workspace already carries *source* as ``solution.py``.

    The verifier materializes from the challenge payload itself (never from a
    local edit), so to test a hostile ``solution.py`` we must rewrite the
    payload file + its manifest digest.
    """
    p = dict(payload)
    files = dict(p["workspace_files"])
    files["solution.py"] = source
    p["workspace_files"] = files
    manifest = []
    for entry in p["workspace_manifest"]:
        entry = dict(entry)
        if entry["path"] == "solution.py":
            entry["sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
        manifest.append(entry)
    p["workspace_manifest"] = manifest
    return p


# ================================================================== P0-1: process boundary

_FRAME_STEALER = (
    "import inspect\n"
    "def solve(*args):\n"
    "    frame = inspect.currentframe()\n"
    "    while frame is not None:\n"
    "        for name in ('expected', 'expecteds', 'expected_list',\n"
    "                     'case', 'cases', 'hidden', 'hidden_tests',\n"
    "                     'expected_values', 'verifier_secret'):\n"
    "            if name in frame.f_locals:\n"
    "                value = frame.f_locals[name]\n"
    "                if value is not None:\n"
    "                    return {'stolen': name}\n"
    "        frame = frame.f_back\n"
    "    return {'stolen': 'nothing'}\n"
)


@pytest.fixture()
def repo_payload():
    payload, _ = generate_with_solution("integrity-a", 1, _SECRET)
    return payload


def test_frame_inspection_cannot_read_expected(repo_payload) -> None:
    """§8.1: a candidate walking caller frames must not obtain expected."""
    ch = _challenge_dict(
        _payload_with_solution(repo_payload, _FRAME_STEALER), "integrity-a", 1, _SECRET
    )
    result = FAMILY.evaluate(ch, {"patch": ""})
    assert not result.valid
    assert result.error_code in (
        ErrorCode.PUBLIC_TEST_FAILURE,
        ErrorCode.HIDDEN_TEST_FAILURE,
    )


def test_monkeypatch_builtins_cannot_affect_parent(repo_payload) -> None:
    """§8.2/8.3: rebinding builtins/json in the candidate process cannot
    change the parent's comparison."""
    malicious = (
        "import builtins, json\n"
        "builtins.open = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('nope'))\n"
        "json.dumps = lambda *a, **k: 'True'\n"
        "json.dump = lambda *a, **k: None\n"
        "json.load = lambda *a, **k: {'cases': []}\n"
        "def solve(*args):\n"
        "    return {'evil': True}\n"
    )
    ch = _challenge_dict(_payload_with_solution(repo_payload, malicious), "integrity-a", 1, _SECRET)
    result = FAMILY.evaluate(ch, {"patch": ""})
    # The result channel is protected by pre-captured driver references; the
    # candidate still cannot pass and verification completes deterministically.
    assert not result.valid
    assert result.error_code is not None


def test_sys_modules_probing_cannot_reach_expected(repo_payload) -> None:
    """§8.4: reading sys.modules / globals of evaluator modules yields nothing."""
    probe = (
        "import sys\n"
        "def solve(*args):\n"
        "    for modname in list(sys.modules):\n"
        "        mod = sys.modules.get(modname)\n"
        "        if mod is None:\n"
        "            continue\n"
        "        for key in dir(mod):\n"
        "            if 'expected' in key.lower() and not key.startswith('_'):\n"
        "                return {'probe': modname + '.' + key}\n"
        "    return {'probe': 'nothing'}\n"
    )
    ch = _challenge_dict(_payload_with_solution(repo_payload, probe), "integrity-a", 1, _SECRET)
    result = FAMILY.evaluate(ch, {"patch": ""})
    assert not result.valid
    assert result.error_code in (
        ErrorCode.PUBLIC_TEST_FAILURE,
        ErrorCode.HIDDEN_TEST_FAILURE,
    )


def test_child_channel_never_carries_hidden_expected_or_secret(repo_payload, monkeypatch) -> None:
    """§8.5: the candidate subprocess stdin/argv/env never contains hidden
    expected values or the verifier secret."""
    import vica.repo.family as family_mod

    probe = (
        "import json, os, sys\n"
        "def solve(*args):\n"
        "    dump = {'argv': list(sys.argv), 'env': dict(os.environ)}\n"
        "    with open('probe.json', 'w') as f:\n"
        "        f.write(json.dumps(dump))\n"
        "    return None\n"
    )
    ch = _challenge_dict(_payload_with_solution(repo_payload, probe), "integrity-a", 1, _SECRET)

    captured: dict = {}

    def _run_spy(cmd, **kwargs):
        captured["argv"] = list(cmd)
        captured["stdin"] = kwargs.get("stdin")
        # Rebuild what the sandbox actually passes to the child: the allowlist
        # environment, never the host copy (no secret can be present).
        captured["env"] = safe_child_environment(kwargs.get("env"))
        return original_run(cmd, **kwargs)

    original_run = family_mod.run_sandboxed
    monkeypatch.setattr(family_mod, "run_sandboxed", _run_spy)
    FAMILY.evaluate(ch, {"patch": ""})

    hidden = hidden_tests_for("integrity-a", 1, _SECRET)
    blob = " ".join(
        [
            json.dumps(captured.get("stdin")),
            json.dumps(captured.get("argv")),
            json.dumps(captured.get("env")),
        ]
    )
    assert _SECRET not in blob
    for case in hidden:
        assert _render(case["expected"]) not in blob
        for arg in case["args"]:
            assert _render(arg) not in blob


def _render(value: object) -> str:
    return json.dumps(value)


def test_candidate_crash_is_process_failure(repo_payload) -> None:
    """A solve that always raises maps to PROCESS_FAILURE, not INTERNAL_ERROR."""
    crashing = "def solve(*args):\n    raise RuntimeError('boom')\n"
    ch = _challenge_dict(_payload_with_solution(repo_payload, crashing), "integrity-a", 1, _SECRET)
    result = FAMILY.evaluate(ch, {"patch": ""})
    assert not result.valid
    assert result.error_code == ErrorCode.PROCESS_FAILURE


def test_candidate_non_serializable_is_process_failure(repo_payload) -> None:
    """A solve returning a non-JSON-serializable value is a candidate process
    failure, never a test comparison."""
    weird = "def solve(*args):\n    return object()\n"
    ch = _challenge_dict(_payload_with_solution(repo_payload, weird), "integrity-a", 1, _SECRET)
    result = FAMILY.evaluate(ch, {"patch": ""})
    assert not result.valid
    assert result.error_code == ErrorCode.PROCESS_FAILURE


def test_malicious_candidate_e2e_bundle(tmp_path) -> None:
    """§55: a real malicious candidate through the full bundle flow is not VALID,
    while reference passes and NoOp fails."""
    from vica.eval.agent_runner import run_agent, run_noop, run_reference
    from vica.eval.verify import verify_evaluation

    eval_dir = tmp_path / "eval"
    prepare_evaluation(
        challenge_type=TYPE_NAME,
        difficulties=[1],
        instances=1,
        seed=5,
        out=eval_dir,
        verifier_secret=_SECRET,
    )

    # Malicious agent: overwrite solution.py with a frame-stealing solve.
    evil_script = tmp_path / "evil.py"
    evil_script.write_text("open('solution.py', 'w').write('''" + _FRAME_STEALER + "''')\n")
    agent_out = tmp_path / "agent"
    summary = run_agent(
        evaluation=eval_dir / "public",
        command=f"{sys.executable} {shlex.quote(str(evil_script))}",
        out=agent_out,
        system_id="evil-agent",
        timeout_s=60.0,
    )
    # The agent produced a patch (a candidate), so the solver step reports one
    # submission; authoritative verification must still mark it invalid.
    assert summary["solved"] == 1
    assert summary["failures"] == []
    result = verify_evaluation(
        evaluation=eval_dir,
        submission=agent_out,
        out=tmp_path / "res",
        system_id="evil-agent",
        trusted_runner_telemetry=True,
    )
    assert result["valid"] == 0

    ref_out = tmp_path / "ref"
    run_reference(
        evaluation=eval_dir / "public",
        out=ref_out,
        system_id="reference",
        verifier_secret=_SECRET,
    )
    ref_result = verify_evaluation(
        evaluation=eval_dir,
        submission=ref_out,
        out=tmp_path / "res-ref",
        system_id="reference",
        trusted_runner_telemetry=True,
    )
    assert ref_result["valid"] == ref_result["challenge_count"] > 0

    noop_out = tmp_path / "noop"
    run_noop(evaluation=eval_dir / "public", out=noop_out, system_id="noop")
    noop_result = verify_evaluation(
        evaluation=eval_dir,
        submission=noop_out,
        out=tmp_path / "res-noop",
        system_id="noop",
        trusted_runner_telemetry=True,
    )
    assert noop_result["valid"] == 0


# ================================================================== P0-2: reference leakage


def test_template_has_no_static_reference() -> None:
    from vica.repo import templates as tpl

    for _name, template in tpl.TEMPLATES.items():
        assert not hasattr(template, "fixed")
        assert not hasattr(template, "buggy")
        assert not hasattr(template, "reference_source")
        assert not hasattr(template, "solution_source")
    for forbidden in ("reference_source", "fixed_source", "solution_source", "correct_source"):
        assert not hasattr(tpl.Template, forbidden)


def test_secretless_generate_has_no_workspace() -> None:
    payload = generate("integrity-a", 1)
    for forbidden in (
        "workspace_files",
        "workspace_manifest",
        "workspace_hash",
        "public_tests",
        "reference_patch",
        "fixed_source",
    ):
        assert forbidden not in payload, f"secretless payload leaked {forbidden!r}"


def test_no_secretless_reference_patch_api() -> None:
    from vica.repo import generator as gen

    for name in dir(gen):
        if name.startswith("_") or name in ("generate_with_solution", "hidden_tests_for"):
            continue
        value = getattr(gen, name)
        if callable(value):
            assert "patch" not in name.lower(), f"unexpected patch API: {name}"
    assert "reference_patch" not in dir(gen)


def test_reference_material_differs_by_secret() -> None:
    """A different verifier secret yields different instance material.

    Template source spaces can be small (e.g. serialization has 8 variants),
    so a single (seed, template) pair may collide by chance; across several
    seeds at least one workspace differs, and the hidden tests (a continuous
    secret-keyed stream) differ for every seed.
    """
    other = "another-secret-zz"
    found = False
    for seed in ("i1", "i2", "i3", "i4", "i5", "i6", "i7", "i8"):
        a, _ = generate_with_solution(seed, 1, _SECRET)
        b, _ = generate_with_solution(seed, 1, other)
        if a["workspace_files"]["solution.py"] != b["workspace_files"]["solution.py"]:
            found = True
            break
    assert found, "no seed produced a secret-dependent workspace source"
    assert hidden_tests_for("integrity-b", 1, _SECRET) != hidden_tests_for("integrity-b", 1, other)


def test_wrong_secret_refused_by_commitment(tmp_path) -> None:
    from vica.verifier.material import verifier_material_commitment

    payload, _ = generate_with_solution("integrity-c", 1, _SECRET)
    ch = _challenge_dict(payload, "integrity-c", 1, "wrong-secret-qq")
    ch["verifier_material_commitment"] = verifier_material_commitment(_SECRET)
    result = FAMILY.evaluate(ch, {"patch": ""})
    assert not result.valid
    assert result.error_code == ErrorCode.INTERNAL_ERROR


# ============================================================== generator semantics


def test_generator_version_bumped() -> None:
    assert GENERATOR_VERSION == "0.2.0"


def test_same_inputs_same_secret_deterministic() -> None:
    a1, s1 = generate_with_solution("seed-x", 1, _SECRET)
    a2, s2 = generate_with_solution("seed-x", 1, _SECRET)
    assert a1 == a2 and s1 == s2


def test_different_seed_different_source_instance() -> None:
    a, sa = generate_with_solution("seed-y1", 2, _SECRET)
    b, sb = generate_with_solution("seed-y2", 2, _SECRET)
    assert a["workspace_files"]["solution.py"] != b["workspace_files"]["solution.py"]
    assert sa["reference_patch"] != sb["reference_patch"]


def test_reference_patch_always_applies_and_matches_fixed() -> None:
    import subprocess

    for seed in ("seed-z1", "seed-z2"):
        payload, sol = generate_with_solution(seed, 1, _SECRET)
        assert sol["fixed_source"]
        assert sol["reference_patch"]
        with tempfile.TemporaryDirectory() as tmp:
            ws = _materialized(payload, Path(tmp))
            subprocess.run(
                ["git", "apply", "-"],
                input=sol["reference_patch"].encode(),
                cwd=str(ws),
                check=True,
            )
            assert (ws / "solution.py").read_text() == sol["fixed_source"]


def test_public_bundle_contains_no_reference_material(tmp_path) -> None:
    eval_dir = tmp_path / "eval"
    prepare_evaluation(
        challenge_type=TYPE_NAME,
        difficulties=[1],
        instances=1,
        seed=9,
        out=eval_dir,
        verifier_secret=_SECRET,
    )
    text = ""
    for f in (
        eval_dir / "public" / "manifest.json",
        eval_dir / "public" / "challenges.jsonl",
        eval_dir / "public" / "README.md",
    ):
        text += f.read_text()
    assert _SECRET not in text
    assert "reference_patch" not in text
    assert "fixed_source" not in text
    assert "hidden_tests" not in text


def test_historical_generator_denied_at_family() -> None:
    """A challenge claiming the withdrawn 0.1.0 generator is refused."""
    payload, _ = generate_with_solution("seed-h", 1, _SECRET)
    ch = _challenge_dict(payload, "seed-h", 1, _SECRET)
    ch["generator_version"] = "0.1.0"
    result = FAMILY.evaluate(ch, {"patch": ""})
    assert not result.valid
    assert result.error_code == ErrorCode.WITHDRAWN_GENERATOR
