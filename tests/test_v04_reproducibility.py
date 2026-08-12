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
import tempfile
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
from vica.protocol.models import ErrorCode
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
    assert tp1.task_pack_id == "repo-v0.1-generated"
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
    assert summary["task_pack_id"] == "repo-v0.1-generated"
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


def test_study_result_bundles_persist_after_return(repo_eval: Path, tmp_path: Path) -> None:
    """§22-25: Result Bundles must survive after ``run_study()`` returns.

    The per-replicate result lives under ``<study-out>/runs/<sid>/r<rep>/result``
    and is never deleted when the study returns.
    """
    out = tmp_path / "study"
    summary = run_study(
        evaluation=repo_eval,
        systems=[
            StudySystem(system_id="reference", kind="reference"),
            StudySystem(system_id="noop", kind="noop"),
        ],
        replicates=2,
        out=out,
        verifier_secret=_SECRET,
    )
    for sid in ("reference", "noop"):
        for rep in range(2):
            result_dir = out / "runs" / sid / f"r{rep}" / "result"
            assert result_dir.is_dir(), f"missing persisted result for {sid} r{rep}"
            assert (result_dir / "manifest.json").is_file()
            assert (result_dir / "results.jsonl").is_file()
            # The bundle is loadable and matches the study's recorded valid count.
            load_result_bundle(result_dir)
    # The summary's recorded path is portable and resolves to the persisted dir.
    ref = summary["systems"]["reference"]
    assert ref["replicates"] == 2


def test_study_replicate_paths_are_portable(repo_eval: Path, tmp_path: Path) -> None:
    """§24: replicate output paths in the summary are relative to the study root,
    never an absolute /tmp path."""
    out = tmp_path / "study"
    summary = run_study(
        evaluation=repo_eval,
        systems=[StudySystem(system_id="noop", kind="noop")],
        replicates=1,
        out=out,
        verifier_secret=_SECRET,
    )
    report = json.loads((out / "study.json").read_text())
    for sid in summary["systems"]:
        sys_sum = report["systems"][sid]
        for rep in sys_sum.get("replicates", []):
            rel = rep["result_bundle"]
            assert not rel.startswith("/"), f"absolute path leaked: {rel}"
            assert rel == f"runs/{sid}/r0/result"


def test_study_rejects_ambiguous_system_id(repo_eval: Path, tmp_path: Path) -> None:
    """system_id is a provenance identity: ambiguous/colliding/unsafe ids are
    rejected (ValueError), never lossily normalized onto a shared path."""
    from vica.eval.study import _safe_component

    # Lossy-cleaner collisions ("a/b" -> "ab") and "." / ".." are rejected.
    for bad in ("a/b", ".", "..", "a b", "../x", "sys/../x", ""):
        with pytest.raises(ValueError):
            _safe_component(bad)

    # Distinct valid ids map to distinct components (no collision).
    assert _safe_component("ab") != _safe_component("a-b")
    assert _safe_component("sys.1") == "sys.1"

    # run_study propagates the rejection before doing any work.
    with pytest.raises(ValueError):
        run_study(
            evaluation=repo_eval,
            systems=[StudySystem(system_id="a/b", kind="noop")],
            replicates=1,
            out=tmp_path / "s",
            verifier_secret=_SECRET,
        )


def test_study_layered_metrics_populated(repo_eval: Path, tmp_path: Path) -> None:
    """§26-27: Study summary populates by_difficulty, by_task_kind and by_template
    from the Result records — real accumulation, not empty objects."""
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
    ref = summary["systems"]["reference"]
    assert ref["by_difficulty"], "by_difficulty must be populated"
    assert ref["by_task_kind"], "by_task_kind must be populated"
    assert ref["by_template"], "by_template must be populated"
    # Reference passes every challenge in every layer.
    for layer in (ref["by_difficulty"], ref["by_task_kind"], ref["by_template"]):
        for label, cell in layer.items():
            assert cell["total"] > 0
            assert cell["valid"] == cell["total"], f"reference not 100% in {label}"
    noop = summary["systems"]["noop"]
    for layer in (noop["by_difficulty"], noop["by_task_kind"], noop["by_template"]):
        for cell in layer.values():
            assert cell["valid"] == 0, "noop must fail every challenge in every layer"


# =================================== benchmark validation (§76-§78)


def test_seed_generalization_changes_identity_and_hidden(repo_eval: Path) -> None:
    """§78: within the *same* template semantics, two different seeds must yield
    different solver-visible and hidden material, while the reference (fixed)
    source still passes every generated case on both seeds."""
    import random

    from vica.repo.templates import (
        TEMPLATES,
        _run_source,
        build_source_instance,
        classify_hidden,
        classify_public,
    )

    for name, template in TEMPLATES.items():
        inst_a = build_source_instance(template, random.Random(f"{name}-instA"))
        inst_b = build_source_instance(template, random.Random(f"{name}-instB"))
        pub_a = classify_public(inst_a, random.Random(f"{name}-seedA"), count=4)
        pub_b = classify_public(inst_b, random.Random(f"{name}-seedB"), count=4)
        hid_a = classify_hidden(inst_a, random.Random(f"{name}-seedA"), count=8)
        hid_b = classify_hidden(inst_b, random.Random(f"{name}-seedB"), count=8)
        # Different seeds → different hidden (discriminating) case sets…
        assert [c["args"] for c in hid_a] != [c["args"] for c in hid_b]
        # …and the reference (fixed) source passes all cases on both seeds.
        for instance, cases in ((inst_a, pub_a + hid_a), (inst_b, pub_b + hid_b)):
            for case in cases:
                assert _run_source(instance.fixed, tuple(case["args"])) == case["expected"]


def test_public_only_probe_fails_hidden(repo_eval: Path) -> None:
    """§77: for every template the buggy (public-only, naive) state passes all
    public cases yet fails at least one hidden case — so hidden tests genuinely
    add discriminative power rather than repeating the public examples."""
    import random

    from vica.repo.templates import (
        TEMPLATES,
        _run_source,
        build_source_instance,
        classify_hidden,
        classify_public,
    )

    rng_public = random.Random("probe-public")
    rng_instances = random.Random("probe-instances")
    rng_hidden = random.Random("probe-hidden")
    for name, template in TEMPLATES.items():
        instance = build_source_instance(
            template, random.Random(f"{name}:{rng_instances.random()}")
        )
        public = classify_public(instance, rng_public, count=4)
        hidden = classify_hidden(instance, rng_hidden, count=8)
        # The naive/buggy solve passes every public case…
        for case in public:
            assert _run_source(instance.buggy, tuple(case["args"])) == case["expected"]
        # …but fails at least one hidden case (public-only overfit cannot pass).
        assert any(
            _run_source(instance.buggy, tuple(c["args"])) != c["expected"]
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
    assert manifest["task_pack_id"] == "repo-v0.1-generated"
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


def test_task_pack_version_is_family_scoped() -> None:
    """Task Pack version is family-scoped: only REPO (whose generator/verifier
    semantics changed) bumps to v2; CSP/SYNTH/OPT keep the default v1. A global
    version bump must not silently re-identify unrelated families."""
    from vica.eval.taskpack import (
        DEFAULT_TASK_PACK_VERSION,
        task_pack_version_for,
    )

    assert DEFAULT_TASK_PACK_VERSION == "1"
    assert task_pack_version_for("repo-v0.1") == TASK_PACK_VERSION == "2"
    assert task_pack_version_for("csp-v0.1") == "1"
    assert task_pack_version_for("synth-v0.1") == "1"
    assert task_pack_version_for("opt-v0.1") == "1"


def test_reverify_rejects_task_pack_version_tamper(repo_eval: Path, tmp_path: Path) -> None:
    """Strict reverify binds task_pack_version at the semantic layer.

    After recomputing the Result manifest's own bundle_hash, a tampered
    ``task_pack_version`` must still be refused — proving the failure comes
    from the version binding, not from an invalid manifest hash.
    """
    from vica.protocol.serialization import stable_hash

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
    manifest_path = res / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["task_pack_version"] = "999"
    manifest["bundle_hash"] = None
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
    """Historical REPO generator 0.1.0 fixture: it LOADS for inspection, but
    authoritative reverify refuses it with the clear withdrawn-generator
    reason (§35 — the 0.1.0 verifier semantics are never re-run or
    reinterpreted under 0.2.0)."""
    from vica.eval.bundle import load_public_challenges, load_public_manifest
    from vica.repo.family import FAMILY
    from vica.repo.generator import VERIFIER_SECRET_KEY

    # (1) The historical bundle still loads and its provenance is readable.
    pub = load_public_manifest(golden_v2)
    assert pub["generator_version"] == "0.1.0"
    challenges = load_public_challenges(golden_v2)
    assert challenges

    # (2) The family-level verifier refuses the old generator outright.
    import json

    with tempfile.TemporaryDirectory():
        material = json.loads(
            (golden_v2 / "private" / "verifier-material.json").read_text()
        )
        challenge_row = json.loads(
            (golden_v2 / "public" / "challenges.jsonl").read_text().strip().splitlines()[0]
        )
        challenge_row[VERIFIER_SECRET_KEY] = material["verifier_secret"]
        result = FAMILY.evaluate(challenge_row, {"patch": ""})
        assert not result.valid
        assert result.error_code == ErrorCode.WITHDRAWN_GENERATOR

    # (3) The authoritative verify path refuses with the explicit withdrawn
    # reason rather than producing a misleading verification run.
    from vica.eval.verify import verify_evaluation

    sub_dir = tmp_path / "golden-noop"
    run_noop(evaluation=golden_v2, out=sub_dir, system_id="noop")
    with pytest.raises(EvaluationFailure, match="withdrawn"):
        verify_evaluation(
            evaluation=golden_v2,
            submission=sub_dir,
            out=tmp_path / "golden-res",
            system_id="noop",
            trusted_runner_telemetry=True,
        )


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