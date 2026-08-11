"""v0.4 Benchmark Validation & Reproducibility tests (docs/REPRODUCIBILITY.md,
"Task Pack", "Execution Profile", "Study").

Covers the v0.4 closed loop: Task Pack identity & versioning, Execution
Profile / environment provenance (names only, never secret values), the
multi-run Study orchestration (replicates + layered metrics), and the Task
Pack binding in both Result Bundle writing and strict reverify. Requirements:
no real model, no network, no hardened sandbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vica.eval.agent_runner import _forwarded_environment, run_noop, run_reference
from vica.eval.bundle import prepare_evaluation
from vica.eval.environment import dependency_environment_hash, execution_profile
from vica.eval.models import EvaluationFailure
from vica.eval.reverify import reverify_bundle
from vica.eval.study import StudySystem, run_study
from vica.eval.taskpack import TASK_PACK_VERSION, derive_task_pack
from vica.eval.verify import load_result_bundle, verify_evaluation
from vica.repo.generator import TYPE_NAME

_SECRET = "v04-secret-0000"


def _prepare(eval_dir: Path, *, instances: int = 2) -> Path:
    prepare_evaluation(
        challenge_type=TYPE_NAME,
        difficulties=[1, 2],
        instances=instances,
        seed=11,
        out=eval_dir,
        verifier_secret=_SECRET,
    )
    return eval_dir


def _public_manifest_hash(eval_dir: Path) -> str:
    pub = json.loads((eval_dir / "public" / "manifest.json").read_text())
    return pub["manifest_hash"]


@pytest.fixture()
def repo_eval(tmp_path: Path) -> Path:
    return _prepare(tmp_path / "eval")


# ================================================================== task pack


def test_task_pack_identity_stable(repo_eval: Path) -> None:
    from vica.eval.bundle import load_public_challenges, load_public_manifest

    pub = load_public_manifest(repo_eval)
    challenges = load_public_challenges(repo_eval)
    tp1 = derive_task_pack(pub, challenges)
    tp2 = derive_task_pack(pub, challenges)
    assert tp1.task_pack_hash == tp2.task_pack_hash
    assert tp1.task_pack_id == "repo-v0.1-core"
    assert tp1.task_pack_version == TASK_PACK_VERSION
    assert tp1.challenge_type == TYPE_NAME


def test_task_pack_hash_changes_when_task_set_changes(repo_eval: Path) -> None:
    from vica.eval.bundle import load_public_challenges, load_public_manifest

    pub = load_public_manifest(repo_eval)
    challenges = load_public_challenges(repo_eval)
    base = derive_task_pack(pub, challenges)

    # A different challenge id (task set) must change the hash.
    mutated = [dict(c, id=c["id"] + "-x") for c in challenges]
    changed = derive_task_pack(pub, mutated)
    assert changed.task_pack_hash != base.task_pack_hash


def test_task_pack_hash_order_independent(repo_eval: Path) -> None:
    from vica.eval.bundle import load_public_challenges, load_public_manifest

    pub = load_public_manifest(repo_eval)
    challenges = load_public_challenges(repo_eval)
    forward = derive_task_pack(pub, challenges)
    reversed_ch = list(reversed(challenges))
    backward = derive_task_pack(pub, reversed_ch)
    assert forward.task_pack_hash == backward.task_pack_hash


# ================================================================= execution


def test_execution_profile_records_environment() -> None:
    profile = execution_profile(
        backend="local",
        timeout_s=30.0,
        passed_env_names=["OPENAI_API_KEY"],
        agent_command="claude -p",
    )
    assert profile["runner_backend"] == "local"
    assert profile["timeout_s"] == 30.0
    # Names only — the (hypothetical) secret value is never recorded.
    assert profile["passed_env_names"] == ["OPENAI_API_KEY"]
    assert "sk-secret-placeholder" not in json.dumps(profile)
    assert "agent_command" in profile
    assert dependency_environment_hash()


def test_execution_profile_never_records_secret_values() -> None:
    os.environ["VICA_TEST_PASS_VALUE"] = "super-secret-value"
    try:
        forwarded = _forwarded_environment(["VICA_TEST_PASS_VALUE"])
        profile = execution_profile(passed_env_names=list(forwarded.keys()))
        dumped = json.dumps(profile)
        assert "super-secret-value" not in dumped
    finally:
        os.environ.pop("VICA_TEST_PASS_VALUE", None)


# ================================================================== study


def test_study_reference_and_noop(repo_eval: Path, tmp_path: Path) -> None:
    out = tmp_path / "study"
    summary = run_study(
        evaluation=repo_eval,
        systems=[
            StudySystem(system_id="reference", kind="reference"),
            StudySystem(system_id="noop", kind="noop"),
        ],
        replicates=1,
        out=out,
        verifier_secret=_SECRET,
    )
    assert summary["task_pack_id"] == "repo-v0.1-core"
    assert set(summary["systems"]) == {"reference", "noop"}

    # Reference must pass every challenge; NoOp must fail every challenge.
    ref = summary["systems"]["reference"]
    noop = summary["systems"]["noop"]
    assert ref["valid"] == ref["challenge_count"] > 0
    assert noop["valid"] == 0
    assert noop["challenge_count"] == ref["challenge_count"]

    # Aggregate study report is written and is canonical JSON.
    report = json.loads((out / "study.json").read_text())
    assert report["task_pack_hash"] == summary["task_pack_hash"]
    assert report["systems"]["reference"]["success_rate"] == 1.0


def test_study_replicates_aggregate(repo_eval: Path, tmp_path: Path) -> None:
    out = tmp_path / "study"
    summary = run_study(
        evaluation=repo_eval,
        systems=[StudySystem(system_id="noop", kind="noop")],
        replicates=3,
        out=out,
        verifier_secret=_SECRET,
    )
    noop = summary["systems"]["noop"]
    assert noop["replicates"] == 3
    report = json.loads((out / "study.json").read_text())
    assert isinstance(report["systems"]["noop"]["median_latency_ms"], (int, float, type(None)))


# =================================== benchmark validation (§76-§78)


def test_seed_generalization_changes_identity_and_hidden(repo_eval: Path) -> None:
    """§78: within the *same* template semantics, two different seeds must yield
    different solver-visible and hidden material, while the reference (fixed)
    source still passes every generated case on both seeds."""
    import random

    from vica.repo.templates import (
        TEMPLATES,
        _run_source,
        classify_hidden,
        classify_public,
    )

    for name, template in TEMPLATES.items():
        pub_a = classify_public(template, random.Random(f"{name}-seedA"), count=4)
        pub_b = classify_public(template, random.Random(f"{name}-seedB"), count=4)
        hid_a = classify_hidden(template, random.Random(f"{name}-seedA"), count=8)
        hid_b = classify_hidden(template, random.Random(f"{name}-seedB"), count=8)
        # Different seeds → different hidden (discriminating) case sets…
        assert [c["args"] for c in hid_a] != [c["args"] for c in hid_b]
        # …and the reference (fixed) source passes all cases on both seeds.
        for case in list(pub_a) + list(hid_a) + list(pub_b) + list(hid_b):
            assert _run_source(template.fixed, tuple(case["args"])) == case["expected"]


def test_public_only_probe_fails_hidden(repo_eval: Path) -> None:
    """§77: for every template the buggy (public-only, naive) state passes all
    public cases yet fails at least one hidden case — so hidden tests genuinely
    add discriminative power rather than repeating the public examples."""
    from vica.repo.templates import (
        TEMPLATES,
        _run_source,
        classify_hidden,
        classify_public,
    )

    rng_public = __import__("random").Random("probe-public")
    rng_hidden = __import__("random").Random("probe-hidden")
    for name, template in TEMPLATES.items():
        public = classify_public(template, rng_public, count=4)
        hidden = classify_hidden(template, rng_hidden, count=8)
        # The naive/buggy solve passes every public case…
        for case in public:
            assert _run_source(template.buggy, tuple(case["args"])) == case["expected"]
        # …but fails at least one hidden case (public-only overfit cannot pass).
        assert any(
            _run_source(template.buggy, tuple(c["args"])) != c["expected"]
            for c in hidden
        ), f"template {name}: public-only naive state passes hidden tests"


# ===================================================== task pack binding


def test_result_bundle_records_task_pack(repo_eval: Path, tmp_path: Path) -> None:
    sub = tmp_path / "noop-sub"
    run_noop(evaluation=repo_eval, out=sub, system_id="noop")
    res = tmp_path / "result"
    verify_evaluation(
        evaluation=repo_eval,
        submission=sub,
        out=res,
        system_id="noop",
        trusted_runner_telemetry=True,
    )
    manifest = load_result_bundle(res)
    assert manifest["task_pack_id"] == "repo-v0.1-core"
    assert manifest["task_pack_version"] == TASK_PACK_VERSION
    assert len(manifest["task_pack_hash"]) == 64


def test_reverify_binds_task_pack(repo_eval: Path, tmp_path: Path) -> None:
    sub = tmp_path / "ref-sub"
    run_reference(
        evaluation=repo_eval,
        out=sub,
        system_id="reference",
        verifier_secret=_SECRET,
    )
    res = tmp_path / "result"
    verify_evaluation(
        evaluation=repo_eval,
        submission=sub,
        out=res,
        system_id="reference",
        trusted_runner_telemetry=True,
    )
    ok = reverify_bundle(res, repo_eval, system_id="reference")
    assert ok["ok"] is True


def test_reverify_detects_tampered_task_pack(repo_eval: Path, tmp_path: Path) -> None:
    sub = tmp_path / "ref-sub"
    run_reference(
        evaluation=repo_eval,
        out=sub,
        system_id="reference",
        verifier_secret=_SECRET,
    )
    res = tmp_path / "result"
    verify_evaluation(
        evaluation=repo_eval,
        submission=sub,
        out=res,
        system_id="reference",
        trusted_runner_telemetry=True,
    )
    # Tamper with the stored task pack hash -> strict reverify must refuse.
    manifest_path = res / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["task_pack_hash"] = "0" * 64
    manifest["bundle_hash"] = None  # recompute below
    from vica.protocol.serialization import stable_hash

    stripped = {k: v for k, v in manifest.items() if k != "bundle_hash"}
    manifest["bundle_hash"] = stable_hash(stripped)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(EvaluationFailure):
        reverify_bundle(res, repo_eval, system_id="reference")


def test_verify_summary_no_task_pack_hash_leak(repo_eval: Path, tmp_path: Path) -> None:
    """The verify summary exposes ids/labels, never the raw task pack hash."""
    sub = tmp_path / "noop-sub"
    run_noop(evaluation=repo_eval, out=sub, system_id="noop")
    res = tmp_path / "result"
    summary = verify_evaluation(
        evaluation=repo_eval,
        submission=sub,
        out=res,
        system_id="noop",
        trusted_runner_telemetry=True,
    )
    assert "task_pack_hash" not in summary


# ============================================ v1/v2 bundle compatibility (§61/§62)

_FIXTURES = Path(__file__).parent / "fixtures" / "protocol"


@pytest.fixture()
def golden_v1() -> Path:
    return _FIXTURES / "golden-v1-csp"


@pytest.fixture()
def golden_v2() -> Path:
    return _FIXTURES / "golden-v2-repo"


def test_golden_v1_and_v2_load(tmp_path: Path, golden_v1: Path, golden_v2: Path) -> None:
    """The committed golden compatibility fixtures (§61) load under the 1.0
    dispatcher: v0.2 Bundle v1 (CSP) and v0.3 Bundle v2 (REPO workspace) are
    routed strictly by their advertised version, never silently reinterpreted.
    """
    from vica.eval.bundle import load_public_manifest
    from vica.eval.models import BUNDLE_FORMAT_VERSION, BUNDLE_FORMAT_VERSION_V2

    assert load_public_manifest(golden_v1)["bundle_format_version"] == BUNDLE_FORMAT_VERSION
    assert load_public_manifest(golden_v2)["bundle_format_version"] == BUNDLE_FORMAT_VERSION_V2


def test_golden_v2_reverify_full_loop(golden_v2: Path, tmp_path: Path) -> None:
    """A historical BUNDLE_FORMAT_VERSION_V2 artifact must be fully reverifiable
    with only its own verifier material (the secret is read from the fixture's
    private bundle, not supplied by the caller)."""
    import json

    from vica.eval.agent_runner import run_reference
    from vica.eval.verify import verify_evaluation

    material = json.loads((golden_v2 / "private" / "verifier-material.json").read_text())
    secret = material["verifier_secret"]
    assert secret

    sub = tmp_path / "ref-sub"
    run_reference(evaluation=golden_v2, out=sub, system_id="reference", verifier_secret=secret)
    res = tmp_path / "result"
    verify_evaluation(
        evaluation=golden_v2,
        submission=sub,
        out=res,
        system_id="reference",
        trusted_runner_telemetry=True,
    )
    ok = reverify_bundle(res, golden_v2, system_id="reference")
    assert ok["ok"] is True


def test_v1_and_v2_bundles_both_load(tmp_path: Path) -> None:
    """v0.2 Bundle v1 and v0.3 Bundle v2 are both 1.0 compatibility targets:
    the dispatcher routes each strictly by its advertised version, and both
    verify + reverify with the same code path.
    """
    from vica.eval.bundle import load_public_manifest
    from vica.eval.models import BUNDLE_FORMAT_VERSION, BUNDLE_FORMAT_VERSION_V2

    # v1: a classic CSP evaluation (no REPO workspace).
    v1 = tmp_path / "v1"
    prepare_evaluation(
        challenge_type="csp-v0.1",
        difficulties=[1],
        instances=1,
        seed=7,
        out=v1,
    )
    assert load_public_manifest(v1)["bundle_format_version"] == BUNDLE_FORMAT_VERSION

    # v2: the REPO workspace evaluation.
    v2 = tmp_path / "v2"
    prepare_evaluation(
        challenge_type=TYPE_NAME,
        difficulties=[1],
        instances=1,
        seed=7,
        out=v2,
        verifier_secret=_SECRET,
    )
    assert load_public_manifest(v2)["bundle_format_version"] == BUNDLE_FORMAT_VERSION_V2