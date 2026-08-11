"""Tests for the LLM system adapter (pure logic, no network)."""

from __future__ import annotations

import json

import pytest

from vica.challenges.csp_v01 import generate
from vica.challenges.synth_v01 import generate as synth_generate
from vica.systems import (
    LLMSolverSystem,
    SynthLLMAgentSystem,
    SynthLLMOneShotSystem,
)
from vica.systems.llm.llm_solver import (
    _estimate_cost_usd,
    build_csp_prompt,
    build_synth_prompt,
    classify_transport_status,
    parse_candidate_json,
    parse_synth_candidate,
)


class TestClassifyTransport:
    @pytest.mark.parametrize(
        "status,text,expected",
        [
            (200, "ok", "success"),
            (408, "slow", "timeout"),
            (429, "rate limited", "timeout"),
            (504, "gateway", "timeout"),
            (500, "boom", "provider_error"),
            (401, "unauthorized", "provider_error"),
            (0, "network_error: timeout", "timeout"),
            (0, "network_error: [Errno 61] Connection refused", "transport_error"),
        ],
    )
    def test_classify(self, status: int, text: str, expected: str) -> None:
        assert classify_transport_status(status, text) == expected


class TestPrompt:
    def test_prompt_includes_vars_domain_constraints(self) -> None:
        payload = generate("llm-seed", 2)
        prompt = build_csp_prompt(payload)
        assert "A0" in prompt
        assert "[0, 31]" in prompt
        assert "Constraints" in prompt

    def test_prompt_deterministic(self) -> None:
        payload = generate("llm-seed", 2)
        assert build_csp_prompt(payload) == build_csp_prompt(payload)

    def test_prompt_renders_each_operator(self) -> None:
        payload = {
            "variables": ["A0", "A1", "A2"],
            "min_value": 0,
            "max_value": 31,
            "constraints": [
                {"op": "eq", "vars": ["A0", "A1"]},
                {"op": "ne", "vars": ["A0", "A2"]},
                {"op": "lt", "vars": ["A0", "A1"]},
                {"op": "add", "vars": ["A0", "A1"], "target": 6},
                {"op": "xor", "vars": ["A0", "A1"], "target": 4},
                {"op": "mod_sum", "vars": ["A0", "A1", "A2"], "mod": 31, "target": 9},
                {"op": "linear", "vars": ["A0", "A1", "A2"], "coeffs": [1, 2, 1], "target": 12},
                {"op": "all_diff", "vars": ["A0", "A1", "A2"]},
            ],
        }
        prompt = build_csp_prompt(payload)
        expected_fragments = [
            "all equal",
            "pairwise unequal",
            "< value(A1)",
            "= 6",
            "XOR value(A1) = 4",
            "mod 31 = 9",
            "1*value(A0) + 2*value(A1) + 1*value(A2) = 12",
            "are all distinct",
        ]
        for fragment in expected_fragments:
            assert fragment in prompt, fragment


class TestParseJson:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('{"A0": 5, "A1": 12}', {"A0": 5, "A1": 12}),
            ('```json\n{"A0": 1}\n```', {"A0": 1}),
            ('Some reasoning text...\n{"A0": 2, "A1": 3}\ntrailing', {"A0": 2, "A1": 3}),
            ("{\"A0\": 5}", {"A0": 5}),
        ],
    )
    def test_parse_json(self, raw: str, expected: dict) -> None:
        assert parse_candidate_json(raw) == expected

    def test_rejects_non_object(self) -> None:
        with pytest.raises(ValueError):
            parse_candidate_json("[1, 2, 3]")
        with pytest.raises(ValueError):
            parse_candidate_json("no json here")
        with pytest.raises(ValueError):
            parse_candidate_json("")


class TestCost:
    def test_cost_estimate(self) -> None:
        assert _estimate_cost_usd(1_000_000, 500_000, 1.0, 2.0) == pytest.approx(2.0)
        # UNKNOWN pricing => UNKNOWN cost (None), never confused with free (0.0).
        assert _estimate_cost_usd(100, 100, None, None) is None


class TestConstructor:
    def test_requires_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VICA_LLM_MODEL", raising=False)
        with pytest.raises(ValueError):
            LLMSolverSystem()

    def test_model_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VICA_LLM_MODEL", "env-model")
        sys_ = LLMSolverSystem()
        assert sys_.model == "env-model"

    def test_model_explicit_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VICA_LLM_MODEL", "env-model")
        sys_ = LLMSolverSystem(model="explicit-model")
        assert sys_.model == "explicit-model"


class TestSolve:
    def test_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VICA_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        sys_ = LLMSolverSystem(model="test-model")
        with pytest.raises(RuntimeError):
            sys_.solve({"payload": generate("llm-seed", 1)})

    def test_mocked_transport_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import vica.systems.llm.llm_solver as mod

        payload = generate("llm-seed", 1)
        expected_candidate = {payload["variables"][0]: 7}

        def fake_transport(**kw):
            text = json.dumps(
                {
                    "choices": [{"message": {"content": json.dumps(expected_candidate)}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 40},
                }
            )
            return 200, text

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(mod, "_chat_completion", fake_transport)
        sys_ = LLMSolverSystem(model="test-model")
        out = sys_.solve({"payload": payload})
        assert out.candidate == expected_candidate
        assert out.metadata["status"] == "success"
        assert out.metadata["input_tokens"] == 120
        assert out.metadata["output_tokens"] == 40
        assert out.metadata["attempts"] == 1
        assert out.metadata["model"] == "test-model"

    def test_retry_on_bad_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import vica.systems.llm.llm_solver as mod

        calls = {"n": 0}

        def fake_transport(**kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return 200, "not json at all"
            return 200, json.dumps(
                {"choices": [{"message": {"content": '{"A0": 3}'}}], "usage": {}}
            )

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(mod, "_chat_completion", fake_transport)
        sys_ = LLMSolverSystem(model="test-model", max_retries=2)
        out = sys_.solve({"payload": generate("llm-seed", 1)})
        assert out.candidate == {"A0": 3}
        assert calls["n"] == 2
        assert out.metadata["attempts"] == 2

    def test_http_error_results_in_no_candidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import vica.systems.llm.llm_solver as mod

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(mod, "_chat_completion", lambda **kw: (500, "boom"))
        sys_ = LLMSolverSystem(model="test-model", max_retries=1)
        out = sys_.solve({"payload": generate("llm-seed", 1)})
        assert out.candidate is None
        assert out.metadata["status"] == "provider_error"
        assert out.metadata["last_error"] == "http_500"

    def test_socket_timeout_is_not_a_wrong_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import vica.systems.llm.llm_solver as mod

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(
            mod,
            "_chat_completion",
            lambda **kw: (0, "network_error: timeout: TimeoutError"),
        )
        sys_ = LLMSolverSystem(model="test-model", max_retries=1)
        out = sys_.solve({"payload": generate("llm-seed", 1)})
        assert out.candidate is None
        assert out.metadata["status"] == "timeout"

    def test_http_429_is_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import vica.systems.llm.llm_solver as mod

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(mod, "_chat_completion", lambda **kw: (429, "rate limit"))
        sys_ = LLMSolverSystem(model="test-model")
        out = sys_.solve({"payload": generate("llm-seed", 1)})
        assert out.candidate is None
        assert out.metadata["status"] == "timeout"

    def test_config_never_exposes_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VICA_LLM_API_KEY", "secret-value")
        sys_ = LLMSolverSystem(model="cfg-model")
        cfg = sys_.config()
        assert cfg["model"] == "cfg-model"
        assert cfg["temperature"] == 0.0
        assert "secret-value" not in str(cfg)


class TestSynthPrompt:
    def _solver_payload(self, seed: str, difficulty: int) -> dict:
        """Solver-visible payload: signature, budget, and public examples.

        Public expected outputs are only assembled by the verifier authority,
        so tests build the payload via ``generate_with_solution`` (which
        requires the verifier secret, as in the Evaluation Mode boundary).
        """
        from vica.challenges.synth_v01 import generate_with_solution

        return generate_with_solution(seed, difficulty, "test-verifier-secret")[0]

    def test_prompt_includes_signature_and_examples(self) -> None:
        payload = self._solver_payload("synth-seed", 2)
        prompt = build_synth_prompt(payload)
        assert "f" in prompt
        assert "x" in prompt
        assert "->" in prompt
        assert "x * 2 + 3" in prompt  # example output format

    def test_prompt_deterministic(self) -> None:
        payload = self._solver_payload("synth-seed", 2)
        assert build_synth_prompt(payload) == build_synth_prompt(payload)


class TestParseSynth:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("x * 2 + 3", "x * 2 + 3"),
            ("```dsl\nx + 1\n```", "x + 1"),
            ("```\nf(x) = x - 2\n```", "x - 2"),
            ('f(x) = x * 3', "x * 3"),
            ("Here is the answer: x % 5", "x % 5"),
        ],
    )
    def test_parse_synth(self, raw: str, expected: str) -> None:
        assert parse_synth_candidate(raw) == expected

    def test_parse_synth_empty(self) -> None:
        assert parse_synth_candidate("") is None
        assert parse_synth_candidate("   ") is None


class TestSynthOneShot:
    def test_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VICA_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        sys_ = SynthLLMOneShotSystem(model="test-model")
        with pytest.raises(RuntimeError):
            sys_.solve({"payload": synth_generate("synth-seed", 1)})

    def test_mocked_transport_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import vica.systems.llm.llm_solver as mod
        from vica.challenges.synth_v01 import generate_with_solution
        from vica.protocol.models import Challenge

        payload, _ = generate_with_solution("synth-seed", 1, "test-verifier-secret")
        challenge = Challenge(
            id="c1",
            type="synth-v0.1",
            generator_version="0.1.0",
            seed="synth-seed",
            difficulty=1,
            payload=payload,
        )

        def fake_transport(**kw):
            assert kw.get("json_mode") is False
            text = json.dumps(
                {
                    "choices": [{"message": {"content": "x + 1"}}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10},
                }
            )
            return 200, text

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(mod, "_chat_completion", fake_transport)
        sys_ = SynthLLMOneShotSystem(model="test-model")
        out = sys_.solve(challenge.model_dump())
        assert out.candidate == {"program": "x + 1"}
        assert out.metadata["strategy"] == "llm-one-shot"
        assert out.metadata["status"] == "success"
        assert out.metadata["input_tokens"] == 90


class TestSynthAgent:
    def test_agent_retries_until_public_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import vica.systems.llm.llm_solver as mod
        from vica.challenges.synth_v01 import generate_with_solution

        payload, sol = generate_with_solution("synth-agent-seed", 1, "test-verifier-secret")
        correct = sol["target_program"]
        wrong = "x + 1"

        calls = {"n": 0}

        def fake_transport(**kw):
            calls["n"] += 1
            prog = wrong if calls["n"] % 2 == 1 else correct
            text = json.dumps(
                {"choices": [{"message": {"content": prog}}], "usage": {}}
            )
            return 200, text

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(mod, "_chat_completion", fake_transport)
        sys_ = SynthLLMAgentSystem(model="test-model", max_rounds=5)
        out = sys_.solve({"payload": payload})
        assert out.candidate == {"program": correct}
        assert out.metadata["strategy"] == "llm-agent"
        assert calls["n"] >= 2

    def test_agent_returns_none_when_never_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import vica.systems.llm.llm_solver as mod
        from vica.challenges.synth_v01 import generate_with_solution
        from vica.protocol.models import Challenge

        payload, _ = generate_with_solution("synth-seed", 1, "test-verifier-secret")
        challenge = Challenge(
            id="c1",
            type="synth-v0.1",
            generator_version="0.1.0",
            seed="synth-seed",
            difficulty=1,
            payload=payload,
        )

        def fake_transport(**kw):
            text = json.dumps(
                {"choices": [{"message": {"content": "999999"}}], "usage": {}}
            )
            return 200, text

        monkeypatch.setenv("VICA_LLM_API_KEY", "test-key")
        monkeypatch.setattr(mod, "_chat_completion", fake_transport)
        sys_ = SynthLLMAgentSystem(model="test-model", max_rounds=2)
        out = sys_.solve(challenge.model_dump())
        assert out.candidate is None
        assert out.metadata["rounds"] == 2
        assert out.metadata["status"] == "parse_error"