"""Tests for the v0.2 Benchmark Research & External Evaluation protocol.

Covers the whole closed loop — Evaluation Bundle, Submission Bundle,
authoritative verification, Result Bundle, strict reverify, plus the
statistics / failure-taxonomy math and the external command solver.

The gate keeps every v0.1 Research-Integrity test green; nothing here
relies on a real LLM or network.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from vica.eval.bundle import (
    inspect_evaluation,
    load_public_challenges,
    load_public_manifest,
    prepare_evaluation,
)
from vica.eval.models import EvaluationFailure, ReportStatus
from vica.eval.reverify import reverify_bundle
from vica.eval.stats import (
    cost_coverage,
    failure_taxonomy,
    latency_distribution,
    paired_comparison,
    wilson_interval,
)
from vica.eval.submission import build_submission_bundle
from vica.eval.verify import load_result_bundle, verify_evaluation

_SECRET_A = "test-secret-aaaa"
_SECRET_B = "test-secret-bbbb"
_PY = sys.executable


def _jsonl_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _prepare(
    out: Path, *, family: str = "csp-v0.1", difficulty: list[int] | None = None,
    instances: int = 2, seed: int = 1, secret: str | None = None,
) -> None:
    prepare_evaluation(
        challenge_type=family,
        difficulties=difficulty or [1],
        instances=instances,
        seed=seed,
        out=out,
        verifier_secret=secret,
    )


@pytest.fixture()
def eval_csp(tmp_path: Path) -> Path:
    prepare_evaluation(
        challenge_type="csp-v0.1",
        difficulties=[1, 2],
        instances=3,
        seed=42,
        out=tmp_path / "eval",
    )
    return tmp_path / "eval"


@pytest.fixture()
def eval_synth(tmp_path: Path) -> Path:
    prepare_evaluation(
        challenge_type="synth-v0.1",
        difficulties=[1],
        instances=2,
        seed=3,
        out=tmp_path / "eval",
        verifier_secret=_SECRET_A,
    )
    return tmp_path / "eval"


# ------------------------------------------------------------------ helpful ds


def _rows_for(evaluation: Path, valid_all: bool = True) -> list[dict]:
    from vica.systems.synth.random_program import RandomProgramSystem

    challenges = load_public_challenges(evaluation)
    rows = []
    for i, ch in enumerate(challenges):
        if ch["type"] == "synth-v0.1":
            out = RandomProgramSystem().solve(ch)
            cand = out.candidate
        else:
            vars_ = ch["payload"].get("variables", [])
            cand = {"assignment": {v: (i % 2 == 0) for i, v in enumerate(vars_)}}
        rows.append({"challenge_id": ch["id"], "candidate": cand, "metadata": {"solver": "test"}})
    return rows


# ================================================================== evaluation


def test_same_config_same_secret_same_challenges(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    prepare_evaluation(
        challenge_type="synth-v0.1", difficulties=[1], instances=2, seed=1, out=a,
        verifier_secret=_SECRET_A,
    )
    prepare_evaluation(
        challenge_type="synth-v0.1", difficulties=[1], instances=2, seed=1, out=b,
        verifier_secret=_SECRET_A,
    )
    assert [c["id"] for c in load_public_challenges(a)] == [
        c["id"] for c in load_public_challenges(b)
    ]


def test_different_secret_different_challenge_ids(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    prepare_evaluation(
        challenge_type="synth-v0.1", difficulties=[1], instances=2, seed=1, out=a,
        verifier_secret=_SECRET_A,
    )
    prepare_evaluation(
        challenge_type="synth-v0.1", difficulties=[1], instances=2, seed=1, out=b,
        verifier_secret=_SECRET_B,
    )
    assert [c["id"] for c in load_public_challenges(a)] != [
        c["id"] for c in load_public_challenges(b)
    ]


def test_public_bundle_contains_no_secret(eval_synth: Path) -> None:
    public = eval_synth / "public"
    text = (
        (public / "manifest.json").read_text()
        + (public / "challenges.jsonl").read_text()
        + (public / "README.md").read_text()
    )
    for forbidden in [_SECRET_A, "verifier_secret", "target_program", "hidden_tests"]:
        assert forbidden not in text, f"public bundle leaked {forbidden!r}"


def test_public_private_commitment_match(eval_synth: Path) -> None:
    pub = load_public_manifest(eval_synth)
    priv = json.loads((eval_synth / "private" / "manifest.json").read_text())
    assert pub["verifier_material_commitment"] == priv["verifier_material_commitment"]
    assert pub["challenges_hash"] == priv["challenges_hash"]


def test_manifest_hash_stable(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    prepare_evaluation(
        challenge_type="csp-v0.1", difficulties=[1], instances=2, seed=9, out=a
    )
    prepare_evaluation(
        challenge_type="csp-v0.1", difficulties=[1], instances=2, seed=9, out=b
    )
    ma = json.loads((a / "public" / "manifest.json").read_text())
    mb = json.loads((b / "public" / "manifest.json").read_text())
    assert ma["manifest_hash"] == mb["manifest_hash"]


def test_tampered_manifest_rejected(eval_csp: Path) -> None:
    manifest_path = eval_csp / "public" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["challenge_count"] = 999
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(EvaluationFailure):
        load_public_manifest(eval_csp)


def test_tampered_challenge_rejected(eval_csp: Path) -> None:
    challenges_path = eval_csp / "public" / "challenges.jsonl"
    lines = challenges_path.read_text().splitlines()
    # rewrite first line with a mutated difficulty
    obj = json.loads(lines[0])
    obj["difficulty"] = 5
    lines[0] = json.dumps(obj)
    challenges_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(EvaluationFailure):
        load_public_challenges(eval_csp)


# ================================================================== submission


def test_unknown_challenge_rejected(eval_csp: Path) -> None:
    rows = _rows_for(eval_csp)
    rows[0]["challenge_id"] = "does-not-exist"
    with pytest.raises(EvaluationFailure):
        build_submission_bundle(evaluation=eval_csp, system_id="s", rows=rows, out=eval_csp / "sub")


def test_duplicate_challenge_rejected(eval_csp: Path) -> None:
    rows = _rows_for(eval_csp)
    rows.append(dict(rows[0]))
    with pytest.raises(EvaluationFailure):
        build_submission_bundle(evaluation=eval_csp, system_id="s", rows=rows, out=eval_csp / "sub")


def test_missing_challenge_is_no_submission(eval_csp: Path) -> None:
    rows = _rows_for(eval_csp)
    build_submission_bundle(evaluation=eval_csp, system_id="s", rows=rows, out=eval_csp / "sub")
    summary = verify_evaluation(
        evaluation=eval_csp, submission=eval_csp / "sub", out=eval_csp / "res", system_id="s"
    )
    assert summary["no_submission"] == 0
    # drop the last submission -> that challenge becomes NO_SUBMISSION
    rows.pop()
    build_submission_bundle(evaluation=eval_csp, system_id="s", rows=rows, out=eval_csp / "sub")
    summary = verify_evaluation(
        evaluation=eval_csp, submission=eval_csp / "sub", out=eval_csp / "res2", system_id="s"
    )
    assert summary["no_submission"] == 1


def test_malformed_candidate_isolated(eval_csp: Path) -> None:
    rows = _rows_for(eval_csp)
    rows[0]["candidate"] = {"assignment": "not-a-dict"}
    build_submission_bundle(evaluation=eval_csp, system_id="s", rows=rows, out=eval_csp / "sub")
    summary = verify_evaluation(
        evaluation=eval_csp, submission=eval_csp / "sub", out=eval_csp / "res", system_id="s"
    )
    # one malformed candidate does not discard the whole batch
    assert summary["challenge_count"] == 6
    results = [
        json.loads(line)
        for line in (eval_csp / "res" / "results.jsonl").read_text().splitlines()
        if line
    ]
    assert results[0]["status"] == ReportStatus.PARSE_ERROR.value


# ================================================================== verify


def test_wrong_private_material_is_evaluator_error(tmp_path: Path) -> None:
    ev = tmp_path / "ev"
    evB = tmp_path / "evB"
    prepare_evaluation(
        challenge_type="synth-v0.1", difficulties=[1], instances=2, seed=3, out=ev,
        verifier_secret=_SECRET_A,
    )
    prepare_evaluation(
        challenge_type="synth-v0.1", difficulties=[1], instances=2, seed=3, out=evB,
        verifier_secret=_SECRET_B,
    )
    rows = _rows_for(ev)
    build_submission_bundle(evaluation=ev, system_id="s", rows=rows, out=tmp_path / "sub")
    # swap public of evB with private of ev (create a mismatched pair)
    import shutil

    shutil.rmtree(evB / "public")
    shutil.copytree(ev / "public", evB / "public")
    with pytest.raises(EvaluationFailure):
        verify_evaluation(evaluation=evB, submission=tmp_path / "sub", out=tmp_path / "res",
                          system_id="s")


@pytest.mark.parametrize("family", ["csp-v0.1", "synth-v0.1", "opt-v0.1"])
def test_full_loop_all_families(tmp_path: Path, family: str) -> None:
    ev = tmp_path / "ev"
    secret = _SECRET_A if family == "synth-v0.1" else None
    prepare_evaluation(
        challenge_type=family, difficulties=[1], instances=2, seed=5, out=ev, verifier_secret=secret
    )
    challenges = load_public_challenges(ev)
    rows = []
    for ch in challenges:
        if family == "synth-v0.1":
            from vica.systems.synth.random_program import RandomProgramSystem

            out = RandomProgramSystem().solve(ch)
            rows.append({"challenge_id": ch["id"], "candidate": out.candidate, "metadata": {}})
        elif family == "opt-v0.1":
            rows.append({"challenge_id": ch["id"], "candidate": None, "metadata": {}})
        else:
            vars_ = ch["payload"].get("variables", [])
            rows.append(
                {
                    "challenge_id": ch["id"],
                    "candidate": {"assignment": {v: True for v in vars_}},
                    "metadata": {},
                }
            )
    build_submission_bundle(evaluation=ev, system_id="s", rows=rows, out=tmp_path / "sub")
    verify_evaluation(evaluation=ev, submission=tmp_path / "sub", out=tmp_path / "res",
                      system_id="s")
    load_result_bundle(tmp_path / "res")
    summary = reverify_bundle(tmp_path / "res", ev)
    assert summary["ok"], summary["mismatches"]


# ================================================================== result bundle


def test_results_are_identical_on_reverify(eval_synth: Path, tmp_path: Path) -> None:
    rows = _rows_for(eval_synth)
    build_submission_bundle(evaluation=eval_synth, system_id="s", rows=rows, out=tmp_path / "sub")
    verify_evaluation(evaluation=eval_synth, submission=tmp_path / "sub", out=tmp_path / "res",
                      system_id="s")
    bundle = tmp_path / "res"
    orig = [
        json.loads(line) for line in (bundle / "results.jsonl").read_text().splitlines() if line
    ]
    summary = reverify_bundle(bundle, eval_synth)
    assert summary["ok"]
    # valid/score/error_code must be identical (telemetry may differ)
    recomputed_metrics = summary["metrics"]
    assert recomputed_metrics["correctness"]["valid"] == sum(1 for r in orig if r["valid"])


def test_result_bundle_has_no_secret(eval_synth: Path, tmp_path: Path) -> None:
    rows = _rows_for(eval_synth)
    build_submission_bundle(evaluation=eval_synth, system_id="s", rows=rows, out=tmp_path / "sub")
    verify_evaluation(evaluation=eval_synth, submission=tmp_path / "sub", out=tmp_path / "res",
                      system_id="s")
    bundle = tmp_path / "res"
    for f in bundle.iterdir():
        if f.is_file():
            assert _SECRET_A not in f.read_text(), f"result bundle leaked secret in {f.name}"


def test_result_bundle_tamper_detected(eval_synth: Path, tmp_path: Path) -> None:
    rows = _rows_for(eval_synth)
    build_submission_bundle(evaluation=eval_synth, system_id="s", rows=rows, out=tmp_path / "sub")
    verify_evaluation(evaluation=eval_synth, submission=tmp_path / "sub", out=tmp_path / "res",
                      system_id="s")
    bundle = tmp_path / "res"
    with (bundle / "results.jsonl").open("a") as fh:
        fh.write('{"challenge_id":"x","tampered":true}\n')
    with pytest.raises(EvaluationFailure):
        load_result_bundle(bundle)


def test_reverify_refuses_wrong_evaluation(eval_synth: Path, tmp_path: Path) -> None:
    rows = _rows_for(eval_synth)
    build_submission_bundle(evaluation=eval_synth, system_id="s", rows=rows, out=tmp_path / "sub")
    verify_evaluation(evaluation=eval_synth, submission=tmp_path / "sub", out=tmp_path / "res",
                      system_id="s")
    other = tmp_path / "other"
    prepare_evaluation(
        challenge_type="synth-v0.1", difficulties=[1], instances=2, seed=3, out=other,
        verifier_secret=_SECRET_B,
    )
    with pytest.raises(EvaluationFailure):
        reverify_bundle(tmp_path / "res", other)


# ================================================================== statistics


def test_wilson_zero_samples() -> None:
    assert wilson_interval(0, 0) == (None, None)


def test_wilson_edge_cases() -> None:
    # 0/n and n/n are fine (clipped to [0,1])
    lo, hi = wilson_interval(0, 5)
    assert lo == 0.0 and 0 <= hi <= 1
    lo, hi = wilson_interval(5, 5)
    assert 0 <= lo <= 1 and hi == 1.0
    # interior symmetric-ish
    lo, hi = wilson_interval(72, 100)
    assert lo < 0.72 < hi


def test_latency_distribution() -> None:
    d = latency_distribution([1, 2, 3, 4, 100])
    assert d["mean"] == 22.0
    assert d["p50"] == 3.0
    assert d["p95"] is not None
    assert latency_distribution([])["n"] == 0


def test_cost_coverage_unknown_stays_unknown() -> None:
    from vica.eval.models import ResultRecord

    records = [
        ResultRecord("a", "csp", "0.1", 1, "s", "sys", True, 1.0, ReportStatus.VALID, metadata={}),
        ResultRecord(
            "b", "csp", "0.1", 1, "s", "sys", True, 1.0, ReportStatus.VALID,
            metadata={"estimated_cost_usd": 0.5},
        ),
    ]
    out = cost_coverage(records)
    assert out["known"] == 1 and out["total"] == 2
    assert out["cost_coverage"] == 0.5


def test_failure_taxonomy_by_difficulty() -> None:
    from vica.eval.models import ResultRecord

    records = [
        ResultRecord("a", "csp", "0.1", 1, "s", "sys", True, 1.0, ReportStatus.VALID),
        ResultRecord("b", "csp", "0.1", 1, "s", "sys", False, 0.0, ReportStatus.NO_SUBMISSION),
        ResultRecord("c", "csp", "0.1", 2, "s", "sys", False, 0.0, ReportStatus.INVALID_SOLUTION),
    ]
    t = failure_taxonomy(records)
    assert t["counts"][ReportStatus.VALID.value] == 1
    assert t["by_difficulty"]["2"]["valid_rate"] == 0.0


def test_paired_comparison() -> None:
    from vica.eval.models import ResultRecord

    def rec(cid: str, valid: bool, score: float) -> ResultRecord:
        status = ReportStatus.VALID if valid else ReportStatus.INVALID_SOLUTION
        return ResultRecord(cid, "csp", "0.1", 1, "s", "sys", valid, score, status)

    a = {c: rec(c, True, float(i)) for i, c in enumerate(["c1", "c2", "c3"])}
    b = {c: rec(c, True, float(i)) for i, c in enumerate(["c1", "c2", "c3"])}
    b["c2"].score = 99.0  # B wins one
    b["c3"].valid = False
    b["c3"].status = ReportStatus.INVALID_SOLUTION
    a["c4"] = rec("c4", False, 0.0)
    b["c4"] = rec("c4", False, 0.0)  # both fail one
    out = paired_comparison("A", a, "B", b)
    assert out["compared"] == 4
    assert out["a_wins"] == 1 and out["b_wins"] == 1 and out["tie"] == 1 and out["both_fail"] == 1


# ================================================================== command solver


def test_command_solver_valid_candidate(eval_csp: Path, tmp_path: Path) -> None:
    from vica.eval.command_solver import solve_with_command

    script = (
        "import json,sys; ch=json.load(sys.stdin)['challenge']; "
        "print(json.dumps({'challenge_id': ch['id'],'candidate': "
        "{'assignment': {v: True for v in ch['payload'].get('variables',[])}},'metadata':{}}))"
    )
    summary = solve_with_command(
        evaluation=eval_csp, command=f"{_PY} -c {script!r}", out=tmp_path / "sub", system_id="cmd"
    )
    assert summary["solved"] == 6


def test_command_solver_malformed_output(eval_csp: Path, tmp_path: Path) -> None:
    from vica.eval.command_solver import solve_with_command

    summary = solve_with_command(
        evaluation=eval_csp, command="echo not-json", out=tmp_path / "sub", system_id="cmd"
    )
    assert summary["solved"] == 0
    assert len(summary["failures"]) == 6


def test_command_solver_nonzero_exit(eval_csp: Path, tmp_path: Path) -> None:
    from vica.eval.command_solver import solve_with_command

    summary = solve_with_command(
        evaluation=eval_csp, command="exit 3", out=tmp_path / "sub", system_id="cmd"
    )
    assert summary["solved"] == 0
    assert summary["failures"][0]["error"] == "nonzero_exit"


def test_command_solver_timeout(eval_csp: Path, tmp_path: Path) -> None:
    from vica.eval.command_solver import solve_with_command

    summary = solve_with_command(
        evaluation=eval_csp, command="sleep 5", out=tmp_path / "sub", system_id="cmd", timeout_s=0.2
    )
    assert summary["solved"] == 0
    assert summary["failures"][0]["error"] == "timeout"


# ============================================ v0.2 stabilization regression tests


def test_command_solver_does_not_inherit_verifier_secret(
    eval_csp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P0: the external command solver must not inherit host secrets."""
    from vica.eval.command_solver import solve_with_command

    for key in (
        "VICA_VERIFIER_SECRET",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "TEST_PRIVATE_TOKEN",
    ):
        monkeypatch.setenv(key, "TOP-SECRET-VICA-MATERIAL")

    script = (
        "import json,sys,os; ch=json.load(sys.stdin)['challenge']; "
        "leak=[k for k in os.environ if 'SECRET' in k or 'TOKEN' in k or 'API_KEY' in k]; "
        "print(json.dumps({'challenge_id': ch['id'],'candidate':"
        "{'assignment': {v: True for v in ch['payload'].get('variables',[])}},'metadata':"
        "{'leaked': leak}}))"
    )
    sub = tmp_path / "sub"
    summary = solve_with_command(
        evaluation=eval_csp, command=f"{_PY} -c {script!r}", out=sub, system_id="cmd"
    )
    assert summary["solved"] == 6
    # None of the host secrets may be visible to the child.
    from vica.eval.submission import load_submission_bundle

    _, loaded = load_submission_bundle(sub, eval_csp)
    for row in loaded:
        leaked = row["metadata"].get("leaked", [])
        assert leaked == [], f"child process inherited host secrets: {leaked}"


def test_command_solver_wrong_challenge_id_rejected(eval_csp: Path, tmp_path: Path) -> None:
    """A returned challenge_id that does not match is a protocol failure."""
    from vica.eval.command_solver import solve_with_command

    script = (
        "import json,sys; ch=json.load(sys.stdin)['challenge']; "
        "print(json.dumps({'challenge_id': 'wrong', 'candidate': {}}))"
    )
    summary = solve_with_command(
        evaluation=eval_csp, command=f"{_PY} -c {script!r}", out=tmp_path / "sub", system_id="cmd"
    )
    assert summary["solved"] == 0
    assert all(f["error"] == "wrong_challenge_id" for f in summary["failures"])


def test_command_solver_latency_recorded(eval_csp: Path, tmp_path: Path) -> None:
    """Runner-measured wall time must flow into ResultRecord.solve_wall_time_ms."""
    from vica.eval.command_solver import solve_with_command

    script = (
        "import json,sys,time; ch=json.load(sys.stdin)['challenge']; time.sleep(0.05); "
        "print(json.dumps({'challenge_id': ch['id'],'candidate':"
        "{'assignment': {v: True for v in ch['payload'].get('variables',[])}}}))"
    )
    sub = tmp_path / "sub"
    summary = solve_with_command(
        evaluation=eval_csp, command=f"{_PY} -c {script!r}", out=sub, system_id="cmd"
    )
    assert summary["solved"] == 6
    assert all(p["wall_time_ms"] > 0 for p in summary["per_challenge"])

    verify_evaluation(
        evaluation=eval_csp,
        submission=sub,
        out=tmp_path / "res",
        # The command-solver artifact is VICA-owned, so its runner telemetry
        # (measured wall time) is trusted provenance.
        trusted_runner_telemetry=True,
    )
    results = _jsonl_rows(tmp_path / "res" / "results.jsonl")
    assert all(r["solve_wall_time_ms"] > 0 for r in results)


def test_failure_taxonomy_not_all_no_submission(eval_csp: Path, tmp_path: Path) -> None:
    """Command-solver failures must not all collapse to NO_SUBMISSION.

    Uses the VICA-owned trusted runner path (as the Command Solver does) so the
    per-challenge solver outcomes are preserved as trusted provenance.
    """
    from vica.eval.submission import build_submission_bundle

    challenges = load_public_challenges(eval_csp)
    statuses = ["timeout", "parse_error", "no_candidate", "nonzero_exit", "output_too_large"]
    rows = []
    for i, ch in enumerate(challenges):
        status = statuses[i % len(statuses)]
        rows.append(
            {
                "challenge_id": ch["id"],
                "candidate": None,
                "metadata": {"_vica_runner": {"solver_status": status, "wall_time_ms": 1.0}},
            }
        )
    sub = tmp_path / "sub"
    build_submission_bundle(
        evaluation=eval_csp, system_id="cmd", rows=rows, out=sub,
        trusted_runner_telemetry=True,
    )
    verify_evaluation(
        evaluation=eval_csp, submission=sub, out=tmp_path / "res",
        trusted_runner_telemetry=True,
    )
    results = _jsonl_rows(tmp_path / "res" / "results.jsonl")
    statuses_seen = {r["status"] for r in results}
    assert "no_submission" not in statuses_seen
    assert {"timeout", "parse_error", "no_candidate", "sandbox_error"} & statuses_seen


def test_verify_rejects_wrong_actual_secret_before_results(tmp_path: Path) -> None:
    """A wrong actual verifier secret is an evaluator error, fail-fast, and
    must not leave a misleading result artifact behind."""
    ev = tmp_path / "eval"
    _prepare(ev, family="synth-v0.1", instances=2, secret=_SECRET_A)
    # Tamper only the actual secret, keeping the declared commitment.
    material = ev / "private" / "verifier-material.json"
    obj = json.loads(material.read_text())
    obj["verifier_secret"] = _SECRET_B
    material.write_text(json.dumps(obj))

    with pytest.raises(EvaluationFailure):
        verify_evaluation(evaluation=ev, submission=tmp_path / "sub", out=tmp_path / "res")
    # inspect reports FAIL (never a traceback) and verify must not leave artifacts.
    info = inspect_evaluation(ev)
    assert info["ok"] is False
    assert not (tmp_path / "res").exists()


def test_reverify_rejects_wrong_actual_secret(tmp_path: Path) -> None:
    from vica.eval.command_solver import solve_with_command

    ev = tmp_path / "eval"
    _prepare(ev, family="synth-v0.1", instances=2, secret=_SECRET_A)
    script = (
        "import json,sys; ch=json.load(sys.stdin)['challenge']; "
        "print(json.dumps({'challenge_id': ch['id'],'candidate': [],'metadata':{}}))"
    )
    sub = tmp_path / "sub"
    solve_with_command(evaluation=ev, command=f"{_PY} -c {script!r}", out=sub, system_id="cmd")
    res = tmp_path / "res"
    verify_evaluation(evaluation=ev, submission=sub, out=res)

    material = ev / "private" / "verifier-material.json"
    obj = json.loads(material.read_text())
    obj["verifier_secret"] = _SECRET_B
    material.write_text(json.dumps(obj))

    with pytest.raises(EvaluationFailure):
        reverify_bundle(res, ev)


def test_unsupported_submission_bundle_version_rejected(eval_csp: Path, tmp_path: Path) -> None:
    from vica.eval.submission import build_submission_bundle

    challenges = load_public_challenges(eval_csp)
    rows = [
        {"challenge_id": ch["id"], "candidate": None, "metadata": {}}
        for ch in challenges
    ]
    sub = tmp_path / "sub"
    build_submission_bundle(evaluation=eval_csp, system_id="x", rows=rows, out=sub)
    manifest = json.loads((sub / "manifest.json").read_text())
    manifest["submission_bundle_version"] = "999"
    (sub / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(EvaluationFailure):
        verify_evaluation(evaluation=eval_csp, submission=sub, out=tmp_path / "res")


def test_unsupported_result_bundle_version_rejected(eval_synth: Path, tmp_path: Path) -> None:
    from vica.eval.submission import build_submission_bundle

    rows = _rows_for(eval_synth)
    sub = tmp_path / "sub"
    build_submission_bundle(evaluation=eval_synth, system_id="x", rows=rows, out=sub)
    res = tmp_path / "res"
    verify_evaluation(evaluation=eval_synth, submission=sub, out=res)
    manifest = json.loads((res / "manifest.json").read_text())
    manifest["result_bundle_version"] = "999"
    (res / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(EvaluationFailure):
        load_result_bundle(res)


def test_unsupported_evaluation_bundle_format_rejected(eval_csp: Path) -> None:
    manifest_path = eval_csp / "public" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundle_format_version"] = "999"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(EvaluationFailure):
        load_public_manifest(eval_csp)


def test_unsupported_generator_version_rejected() -> None:
    from vica.eval.bundle import validate_generator_version

    with pytest.raises(EvaluationFailure):
        validate_generator_version(
            {"challenge_type": "csp-v0.1"}, "csp-v0.1", "0.0.1"
        )


def test_challenge_row_generator_version_mismatch_rejected(tmp_path: Path) -> None:
    _prepare(tmp_path / "eval", family="csp-v0.1", instances=1)
    challenges_path = tmp_path / "eval" / "public" / "challenges.jsonl"
    lines = challenges_path.read_text().strip().splitlines()
    obj = json.loads(lines[0])
    obj["generator_version"] = "0.0.1"
    challenges_path.write_text("\n".join(json.dumps(o) for o in [obj]) + "\n")
    info = inspect_evaluation(tmp_path / "eval")
    assert info["ok"] is False
    assert any("generator_version" in issue for issue in info["issues"])


def test_result_bundle_path_traversal_rejected(eval_synth: Path, tmp_path: Path) -> None:
    from vica.eval.submission import build_submission_bundle
    from vica.protocol.serialization import stable_hash

    rows = _rows_for(eval_synth)
    sub = tmp_path / "sub"
    build_submission_bundle(evaluation=eval_synth, system_id="x", rows=rows, out=sub)
    res = tmp_path / "res"
    verify_evaluation(evaluation=eval_synth, submission=sub, out=res)
    manifest = json.loads((res / "manifest.json").read_text())
    manifest["files"]["../../outside.txt"] = "sha256:" + "0" * 64
    # Recompute the bundle hash so the *path* check (not the hash check) is what
    # rejects the malicious entry.
    without = {k: v for k, v in manifest.items() if k != "bundle_hash"}
    manifest["bundle_hash"] = stable_hash(without)
    (res / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(EvaluationFailure):
        load_result_bundle(res)


def test_result_bundle_symlink_escape_rejected(
    eval_synth: Path, tmp_path: Path
) -> None:
    from vica.eval.submission import build_submission_bundle

    rows = _rows_for(eval_synth)
    sub = tmp_path / "sub"
    build_submission_bundle(evaluation=eval_synth, system_id="x", rows=rows, out=sub)
    res = tmp_path / "res"
    verify_evaluation(evaluation=eval_synth, submission=sub, out=res)
    os.remove(res / "results.jsonl")
    os.symlink(tmp_path / "outside", res / "results.jsonl")
    with pytest.raises(EvaluationFailure):
        load_result_bundle(res)


def test_submission_exceeds_max_submissions_rejected(
    eval_csp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vica.eval.submission as submission_mod

    challenges = load_public_challenges(eval_csp)
    rows = [{"challenge_id": ch["id"], "candidate": None, "metadata": {}} for ch in challenges]
    sub = tmp_path / "sub"
    submission_mod.build_submission_bundle(evaluation=eval_csp, system_id="x", rows=rows, out=sub)
    # Force a tiny limit so 6 rows exceed it.
    monkeypatch.setattr(submission_mod, "MAX_SUBMISSIONS", 3)
    with pytest.raises(EvaluationFailure):
        submission_mod.load_submission_bundle(sub, eval_csp)


def test_result_bundle_oversized_file_rejected(
    eval_synth: Path, tmp_path: Path
) -> None:
    from vica.eval.submission import build_submission_bundle

    rows = _rows_for(eval_synth)
    sub = tmp_path / "sub"
    build_submission_bundle(evaluation=eval_synth, system_id="x", rows=rows, out=sub)
    res = tmp_path / "res"
    verify_evaluation(evaluation=eval_synth, submission=sub, out=res)
    with (res / "results.jsonl").open("a") as fh:
        fh.write("x" * 100_000 + "\n")
    with pytest.raises(EvaluationFailure):
        load_result_bundle(res)


def test_package_version_matches_pyproject() -> None:
    import tomllib

    import vica

    with open("pyproject.toml", "rb") as fh:
        pyproject = tomllib.load(fh)
    assert vica.__version__ == pyproject["project"]["version"] == "0.4.0"


# ========================================== v0.2 final freeze regression tests


def _write_and_rehash_result_bundle(bundle: Path, manifest: dict) -> None:
    """Persist a modified manifest and recompute its bundle_hash so the
    manifest is internally consistent. The *content* (not the hash) must be
    what the caller expects to reject the bundle."""
    from vica.protocol.serialization import stable_hash

    manifest_path = bundle / "manifest.json"
    without = {k: v for k, v in manifest.items() if k != "bundle_hash"}
    manifest["bundle_hash"] = stable_hash(without)
    manifest_path.write_text(json.dumps(manifest))


def _result_bundle(eval_sel: Path, tmp_path: Path) -> Path:
    from vica.eval.submission import build_submission_bundle

    sub = tmp_path / "sub"
    build_submission_bundle(evaluation=eval_sel, system_id="x", rows=_rows_for(eval_sel), out=sub)
    res = tmp_path / "res"
    verify_evaluation(evaluation=eval_sel, submission=sub, out=res)
    return res


def test_untrusted_vica_runner_metadata_is_stripped(eval_csp: Path, tmp_path: Path) -> None:
    """A file-exchange Submission may never forge ``_vica_*`` runner telemetry.

    Solver rows carrying a fabricated ``_vica_runner`` must be treated as
    untrusted on the file-exchange path: the reserved key is stripped, so the
    forged latency / status cannot become trusted runner provenance.
    """
    from vica.eval.submission import load_submission_bundle

    challenges = load_public_challenges(eval_csp)
    rows = [
        {
            "challenge_id": ch["id"],
            "candidate": None,
            "metadata": {
                "_vica_runner": {"solver_status": "timeout", "wall_time_ms": 99999999},
                "model": "untrusted",
            },
        }
        for ch in challenges
    ]
    sub = tmp_path / "sub"
    # Default (file-exchange) path: not trusted runner telemetry.
    build_submission_bundle(evaluation=eval_csp, system_id="x", rows=rows, out=sub)
    _, loaded = load_submission_bundle(sub, eval_csp)
    for row in loaded:
        assert "_vica_runner" not in row["metadata"], "untrusted solver forged _vica_runner"
        # Non-reserved solver metadata is preserved (still untrusted self-report).
        assert row["metadata"].get("model") == "untrusted"


def test_untrusted_forged_runner_not_used_as_status(eval_csp: Path, tmp_path: Path) -> None:
    """A forged ``_vica_runner`` on a disabled candidate must NOT become TIMEOUT.

    The forged "timeout" is stripped, so the challenge is verified normally
    (missing candidate -> INVALID_SOLUTION on the authoritative path), never
    reported as a runner timeout.
    """
    from vica.eval.submission import build_submission_bundle

    challenges = load_public_challenges(eval_csp)
    rows = [
        {
            "challenge_id": ch["id"],
            "candidate": None,
            "metadata": {"_vica_runner": {"solver_status": "timeout", "wall_time_ms": 99999999}},
        }
        for ch in challenges
    ]
    sub = tmp_path / "sub"
    build_submission_bundle(evaluation=eval_csp, system_id="x", rows=rows, out=sub)
    verify_evaluation(evaluation=eval_csp, submission=sub, out=tmp_path / "res")
    results = _jsonl_rows(tmp_path / "res" / "results.jsonl")
    assert all(r["status"] != ReportStatus.TIMEOUT.value for r in results)
    assert all(r.get("solve_wall_time_ms", 0) == 0 for r in results)


def test_reverify_compares_status(eval_synth: Path, tmp_path: Path) -> None:
    """Same valid/score/error_code but different status must be a mismatch.

    TIMEOUT vs NO_CANDIDATE can both be valid=False / score=0 / error_code=None.
    """
    import hashlib

    from vica.protocol.serialization import stable_hash

    res = _result_bundle(eval_synth, tmp_path)
    results_path = res / "results.jsonl"
    results = _jsonl_rows(results_path)
    # Flip the first stored status to a different failure semantics.
    mutated = list(results)
    mutated[0] = {**mutated[0], "status": ReportStatus.TIMEOUT.value}
    results_path.write_text("\n".join(json.dumps(r) for r in mutated) + "\n")

    manifest_path = res / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["results.jsonl"] = "sha256:" + hashlib.sha256(
        results_path.read_bytes()
    ).hexdigest()
    without = {k: v for k, v in manifest.items() if k != "bundle_hash"}
    manifest["bundle_hash"] = stable_hash(without)
    manifest_path.write_text(json.dumps(manifest))

    summary = reverify_bundle(res, eval_synth)
    assert summary["ok"] is False
    assert any("stored_status" in m for m in summary["mismatches"])


def test_reverify_rejects_tampered_challenge_content(
    eval_synth: Path, tmp_path: Path
) -> None:
    """Re-hashing a tampered challenges.jsonl must not bypass strict reverify.

    The Result Bundle's internal hashes are made consistent, but stored
    challenge *content* no longer matches the authoritative evaluation's
    challenges_hash, so reverify must refuse.
    """
    import hashlib

    from vica.protocol.serialization import stable_hash

    res = _result_bundle(eval_synth, tmp_path)
    # Tamper the stored challenge payload and re-hash it internally.
    challenges_path = res / "challenges.jsonl"
    altered = _jsonl_rows(challenges_path)
    altered[0] = {**altered[0], "difficulty": 999}
    challenges_path.write_text("\n".join(json.dumps(c) for c in altered) + "\n")

    manifest_path = res / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["challenges.jsonl"] = "sha256:" + hashlib.sha256(
        challenges_path.read_bytes()
    ).hexdigest()
    without = {k: v for k, v in manifest.items() if k != "bundle_hash"}
    manifest["bundle_hash"] = stable_hash(without)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(EvaluationFailure):
        reverify_bundle(res, eval_synth)


def test_result_bundle_missing_required_file_rejected(
    eval_synth: Path, tmp_path: Path
) -> None:
    """Omitting a required Result Bundle file (plus its manifest entry) fails."""
    res = _result_bundle(eval_synth, tmp_path)
    os.remove(res / "metrics.json")
    manifest_path = res / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["files"]["metrics.json"]
    _write_and_rehash_result_bundle(res, manifest)
    with pytest.raises(EvaluationFailure):
        load_result_bundle(res)


def test_result_bundle_malformed_hash_rejected(eval_synth: Path, tmp_path: Path) -> None:
    """A malformed file hash like ``abc`` must be rejected, not skipped."""
    res = _result_bundle(eval_synth, tmp_path)
    manifest_path = res / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["results.jsonl"] = "abc"
    _write_and_rehash_result_bundle(res, manifest)
    with pytest.raises(EvaluationFailure):
        load_result_bundle(res)


def test_result_manifest_symlink_rejected_before_read(eval_synth: Path, tmp_path: Path) -> None:
    """A manifest.json that is a symlink must be rejected, not followed."""
    res = _result_bundle(eval_synth, tmp_path)
    os.remove(res / "manifest.json")
    os.symlink(tmp_path / "outside", res / "manifest.json")
    with pytest.raises(EvaluationFailure):
        load_result_bundle(res)


def test_submission_manifest_size_bounded(eval_csp: Path, tmp_path: Path) -> None:
    """A submission manifest larger than MAX_MANIFEST_BYTES is rejected."""
    import vica.eval.submission as submission_mod

    challenges = load_public_challenges(eval_csp)
    rows = [{"challenge_id": ch["id"], "candidate": None, "metadata": {}} for ch in challenges]
    sub = tmp_path / "sub"
    submission_mod.build_submission_bundle(evaluation=eval_csp, system_id="x", rows=rows, out=sub)
    # Bloat the manifest beyond a tiny synthetic limit.
    manifest_path = sub / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["padding"] = "x" * 4096
    manifest_path.write_text(json.dumps(manifest))
    submission_mod.MAX_MANIFEST_BYTES = 1024
    with pytest.raises(EvaluationFailure):
        submission_mod.load_submission_bundle(sub, eval_csp)


def test_command_solver_empty_stdout_is_no_candidate(
    eval_csp: Path, tmp_path: Path
) -> None:
    """Empty solver output classifies as NO_CANDIDATE, not PARSE_ERROR."""
    from vica.eval.command_solver import solve_with_command

    sub = tmp_path / "sub"
    summary = solve_with_command(evaluation=eval_csp, command="true", out=sub, system_id="cmd")
    assert summary["solved"] == 0
    assert all(f["error"] == "no_candidate" for f in summary["failures"])
    verify_evaluation(
        evaluation=eval_csp, submission=sub, out=tmp_path / "res", trusted_runner_telemetry=True
    )
    results = _jsonl_rows(tmp_path / "res" / "results.jsonl")
    assert all(r["status"] == ReportStatus.NO_CANDIDATE.value for r in results)


def test_command_solver_preserves_solver_metadata(
    eval_csp: Path, tmp_path: Path
) -> None:
    """Solver-supplied metadata is preserved for provenance but not authoritative."""
    from vica.eval.command_solver import solve_with_command

    script = (
        "import json,sys; ch=json.load(sys.stdin)['challenge']; "
        "print(json.dumps({'challenge_id': ch['id'],'candidate':"
        "{'assignment': {v: True for v in ch['payload'].get('variables',[])}},"
        "'metadata': {'model': 'test-model', 'attempts': 3}}))"
    )
    sub = tmp_path / "sub"
    solve_with_command(
        evaluation=eval_csp, command=f"{_PY} -c {script!r}", out=sub, system_id="cmd"
    )
    verify_evaluation(
        evaluation=eval_csp, submission=sub, out=tmp_path / "res", trusted_runner_telemetry=True
    )
    results = _jsonl_rows(tmp_path / "res" / "results.jsonl")
    for r in results:
        meta = r["metadata"]
        # Solver self-report preserved under its own untrusted key.
        assert meta["solver_metadata"]["model"] == "test-model"
        assert meta["solver_metadata"]["attempts"] == 3
        # And it must not leak into the authoritative runner telemetry surface.
        assert set(meta["solver_metadata"]) & {
            "_vica_runner",
            "status",
            "challenge_id",
        } == set()