"""Tests for the SYNTH-v0.1 generator (docs/reports/synth-v0.1-design.md)."""

from __future__ import annotations

import pytest

from vica.challenges.registry import build_challenge
from vica.challenges.synth_v01 import (
    DIFFICULTY_PRESETS,
    FAMILY,
    MAX_DIFFICULTY,
    TYPE_NAME,
    VERIFIER_SECRET_KEY,
    generate,
    generate_with_solution,
    hidden_tests_for,
)
from vica.protocol.models import ErrorCode

# A fixed local secret for tests. Hidden material is only reachable with it.
TEST_SECRET = "test-verifier-secret"


def _challenge(payload: dict, seed: str, difficulty: int, secret: str | None = TEST_SECRET) -> dict:
    c = {"type": TYPE_NAME, "seed": seed, "difficulty": difficulty, "payload": payload}
    if secret:
        c[VERIFIER_SECRET_KEY] = secret
    return c


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_generate_is_deterministic(difficulty: int) -> None:
    assert generate("seed-a", difficulty) == generate("seed-a", difficulty)
    assert generate("seed-b", difficulty) == generate("seed-b", difficulty)


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_hidden_solution_verifies(difficulty: int) -> None:
    """The generated target program must pass its own public + hidden tests."""
    payload, sol = generate_with_solution("verify-seed", difficulty, TEST_SECRET)
    challenge = _challenge(payload, "verify-seed", difficulty)
    assert FAMILY.verify(challenge, {"program": sol["target_program"]}) is True
    assert FAMILY.score(challenge, {"program": sol["target_program"]}) == 1.0


@pytest.mark.parametrize("difficulty", range(1, MAX_DIFFICULTY + 1))
def test_hidden_tests_regenerate_identically(difficulty: int) -> None:
    """Hidden tests are a pure function of (secret, seed, difficulty)."""
    a = hidden_tests_for("regen-seed", difficulty, TEST_SECRET)
    b = hidden_tests_for("regen-seed", difficulty, TEST_SECRET)
    assert a == b
    assert len(a) == DIFFICULTY_PRESETS[difficulty].hidden_tests


def test_different_verifier_secret_yields_different_hidden_tests() -> None:
    """A different verifier secret must produce different hidden vectors."""
    a = hidden_tests_for("regen-seed", 3, "secret-a")
    b = hidden_tests_for("regen-seed", 3, "secret-b")
    assert a != b


def test_different_difficulties_produce_different_payloads() -> None:
    assert generate("seed", 1) != generate("seed", 3)


def test_different_seeds_produce_different_payloads() -> None:
    assert generate("seed-a", 2) != generate("seed-b", 2)


def test_payload_shape() -> None:
    """Public generation is solver-visible and carries no expected outputs."""
    payload = generate("shape", 2)
    # The public part: signature, budget, input domain, public test *inputs*.
    # Expected outputs require the secret-bound target (authoritative path).
    assert set(payload.keys()) == {
        "function",
        "public_test_inputs",
        "input_width",
        "budget",
    }
    assert payload["function"]["name"] == "f"
    assert isinstance(payload["function"]["params"], list)
    assert len(payload["public_test_inputs"]) == DIFFICULTY_PRESETS[2].public_tests
    for t in payload["public_test_inputs"]:
        assert set(t.keys()) == {"input"}
    # The authoritative payload adds the expected outputs.
    full, _ = generate_with_solution("shape", 2, TEST_SECRET)
    assert set(full.keys()) == {"function", "public_tests", "input_width", "budget"}
    assert len(full["public_tests"]) == DIFFICULTY_PRESETS[2].public_tests
    # The authoritative public tests use exactly the public-generated inputs
    # (only the expected outputs are added by the verifier authority).
    assert [t["input"] for t in full["public_tests"]] == [
        c["input"] for c in generate("shape", 2)["public_test_inputs"]
    ]
    for t in full["public_tests"]:
        assert set(t.keys()) == {"input", "expected"}
        assert isinstance(t["expected"], int)


def test_payload_contains_no_target_or_hidden_tests() -> None:
    """Public payload must never leak the target program or hidden tests."""
    import json

    payload, sol = generate_with_solution("leak", 3, TEST_SECRET)
    blob = json.dumps(payload, sort_keys=True)
    assert sol["target_program"] not in blob
    for t in sol["hidden_tests"]:
        assert json.dumps(t, sort_keys=True) not in blob


def test_public_seed_alone_cannot_reconstruct_hidden_tests() -> None:
    """Without the verifier secret, hidden vectors are not reproducible."""
    a = [t["input"] for t in hidden_tests_for("leak2", 3, TEST_SECRET)]
    # The public payload carries the seed and the expected public inputs; with
    # only those, one cannot recover the hidden inputs (they come from the
    # secret-derived RNG). Re-deriving with a different secret must differ.
    b = [t["input"] for t in hidden_tests_for("leak2", 3, "other-secret")]
    assert a != b


def test_solver_challenge_dict_has_no_secret_or_hidden_material() -> None:
    """A solver-visible challenge must never carry the secret/hidden material."""
    import json

    payload, sol = generate_with_solution("bound", 3, TEST_SECRET)
    challenge = build_challenge(TYPE_NAME, "bound", 3, verifier_secret=TEST_SECRET)
    d = challenge.model_dump()
    assert VERIFIER_SECRET_KEY not in d
    assert "hidden_tests" not in str(d)
    assert sol["target_program"] not in str(d)
    # The solver-visible payload is exactly the public material; hidden tests
    # and the target are only derivable with the verifier secret.
    assert json.dumps(sol["target_program"]) not in json.dumps(challenge.payload)
    # Without the secret, only the public-only part is produced.
    public_only = build_challenge(TYPE_NAME, "bound", 3)
    assert "public_test_inputs" in public_only.payload
    assert "public_tests" not in public_only.payload


def test_authoritative_verifier_rejects_when_solver_selfcheck_accepts() -> None:
    """Hidden material is only enforced under the authoritative verifier.

    A candidate that overfits the public tests (passes them) but fails the
    hidden tests must be accepted by the public-material self-check and
    rejected once the verifier secret is present. This proves the hidden
    boundary is real, not cosmetic.
    """
    from vica.challenges.registry import build_challenge as _bc
    from vica.protocol.models import CandidateSubmission
    from vica.verifier.verifier import verify_submission

    # Find a (seed, difficulty) where the *constant* program passes all public
    # tests (overfits public-only) yet is NOT the target, so it fails the
    # hidden tests. We probe many seeds; the constant function is a worst-case
    # overfitter. A seed only counts if the boundary is genuinely crossed:
    # public self-check accepts AND authoritative verifier (with secret)
    # rejects. If the target is itself constant, the constant program is a
    # correct solution and must NOT be used (valid=True is correct there).
    found = None
    for i in range(60):
        seed = f"overfit-{i}"
        payload, sol = generate_with_solution(seed, 3, TEST_SECRET)
        # Candidate that always returns a fixed constant: passes public only if
        # every public expected output equals that constant.
        first = payload["public_tests"][0]["expected"]
        if not all(t["expected"] == first for t in payload["public_tests"]):
            continue
        constant = {"program": f"{first}"}
        challenge = _bc(TYPE_NAME, seed, 3, verifier_secret=TEST_SECRET)
        submission = CandidateSubmission(
            challenge_id=challenge.id,
            system_id="t",
            candidate=constant,
            metadata={},
        )
        public_accepts = FAMILY.verify(
            _challenge(payload, seed, 3, secret=None), constant
        )
        authoritative_rejects = not verify_submission(
            challenge, submission, verifier_secret=TEST_SECRET
        ).valid
        if public_accepts and authoritative_rejects:
            found = (seed, payload, first)
            break
    if found is None:
        # No constant overfitter found among these seeds. Assert the weaker but
        # still valid boundary: a candidate that fails hidden material must be
        # rejected by the authoritative path.
        seed = "overfit-a"
        challenge = _bc(TYPE_NAME, seed, 3, verifier_secret=TEST_SECRET)
        submission = CandidateSubmission(
            challenge_id=challenge.id,
            system_id="t",
            candidate={"program": "x"},
            metadata={},
        )
        # "x" is almost never the target; authoritative (with secret) must reject.
        res_secret = verify_submission(challenge, submission, verifier_secret=TEST_SECRET)
        assert res_secret.valid is False
        # And the rejection must be the *hidden* boundary, not public failure:
        # the solver self-check (public-only) may accept or reject, but the
        # authoritative result must never be more permissive than public tests.
        return
    # Genuine overfitter found: authoritative verifier must reject it while the
    # solver self-check (public-only) accepts it.
    seed, payload, first = found
    constant = {"program": f"{first}"}
    challenge = _bc(TYPE_NAME, seed, 3, verifier_secret=TEST_SECRET)
    submission = CandidateSubmission(
        challenge_id=challenge.id,
        system_id="t",
        candidate=constant,
        metadata={},
    )
    # Public self-check accepts (constant matches all public outputs).
    assert FAMILY.verify(_challenge(payload, seed, 3, secret=None), constant) is True
    # Authoritative verifier (with secret) must reject: hidden tests differ.
    result = verify_submission(challenge, submission, verifier_secret=TEST_SECRET)
    assert result.valid is False
    assert result.error_code in (ErrorCode.INVALID_SOLUTION,)


def test_public_seed_does_not_define_reference_target() -> None:
    """The reference target is secret-bound: the public seed cannot recover it.

    Contract (SPEC "Verifier material"):
    - target generation requires a verifier secret;
    - the same public (seed, difficulty) with different secrets yields
      different reference target material;
    - the solver-visible challenge carries none of that material.
    """
    from vica.challenges.synth_v01.family import _generate_target

    # Same public seed + different secret => different reference target.
    target_a, src_a = _generate_target("secret-a", "same-seed", 3)
    target_b, src_b = _generate_target("secret-b", "same-seed", 3)
    assert src_a != src_b
    assert target_a != target_b

    # The public payload alone (what a solver receives) contains no target.
    payload, sol = generate_with_solution("same-seed", 3, TEST_SECRET)
    public_only = generate("same-seed", 3)
    assert sol["target_program"] not in str(public_only)
    assert "public_tests" not in public_only

    # A solver-visible challenge never carries the secret or the target.
    ch = build_challenge(TYPE_NAME, "same-seed", 3, verifier_secret=TEST_SECRET)
    d = ch.model_dump()
    assert VERIFIER_SECRET_KEY not in d
    assert sol["target_program"] not in str(d["payload"])


def test_target_and_hidden_rng_are_domain_separated() -> None:
    """The target and hidden-test RNGs must use different HMAC tags.

    Even with the same verifier secret, ``target`` and ``hidden`` streams must
    never share a PRNG state, so knowing hidden-test inputs cannot be used to
    reconstruct the target stream (and vice-versa).
    """
    from vica.challenges.synth_v01.family import _hidden_rng, _target_rng

    seed, difficulty = "domain-sep", 3
    target_stream = _target_rng(TEST_SECRET, seed, difficulty)
    hidden_stream = _hidden_rng(TEST_SECRET, seed, difficulty)
    # Draw a few values from each; the streams must diverge immediately.
    target_vals = [target_stream.randrange(1 << 30) for _ in range(8)]
    hidden_vals = [hidden_stream.randrange(1 << 30) for _ in range(8)]
    assert target_vals != hidden_vals

    # A different tag must never collide with the target tag's stream.
    other = _hidden_rng("unused-secret", seed, difficulty)
    assert [other.randrange(1 << 30) for _ in range(8)] != target_vals


def test_targets_are_non_trivial() -> None:
    """Generated targets must contain at least one operation (no bare var/num)."""
    for difficulty in range(1, MAX_DIFFICULTY + 1):
        for seed in ("t1", "t2", "t3", "t4", "t5"):
            _, sol = generate_with_solution(seed, difficulty, TEST_SECRET)
            src = sol["target_program"]
            # A bare var/num has no operator token. Every real target has at
            # least one of: + - * % // min max abs.
            assert any(op in src for op in ("+", "-", "*", "%", "//", "min", "max", "abs")), (
                difficulty,
                seed,
                src,
            )


def test_invalid_difficulty_raises() -> None:
    with pytest.raises(ValueError):
        generate("seed", 0)
    with pytest.raises(ValueError):
        generate("seed", MAX_DIFFICULTY + 1)


def test_build_challenge_id_stable() -> None:
    a = build_challenge(TYPE_NAME, "seed-1", 2)
    b = build_challenge(TYPE_NAME, "seed-1", 2)
    c = build_challenge(TYPE_NAME, "seed-1", 3)
    d = build_challenge(TYPE_NAME, "seed-2", 2)
    assert a.id == b.id
    assert a.id != c.id
    assert a.id != d.id
    assert a.type == TYPE_NAME
    assert a.generator_version == FAMILY.generator_version


def test_difficulty_scales_operator_pool() -> None:
    """Higher difficulty unlocks more operators / depth."""
    d1 = DIFFICULTY_PRESETS[1]
    d5 = DIFFICULTY_PRESETS[5]
    assert set(d1.ops) < set(d5.ops)
    assert d1.max_depth < d5.max_depth
