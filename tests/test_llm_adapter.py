"""Tests for the LLM system adapter (pure logic, no network)."""

from __future__ import annotations

import json

import pytest

from vica.challenges.csp_v01 import generate
from vica.systems import LLMSolverSystem
from vica.systems.llm.llm_solver import (
    _estimate_cost_usd,
    build_csp_prompt,
    parse_candidate_json,
)


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
        assert _estimate_cost_usd(100, 100, None, None) == 0.0


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
        assert out.metadata["last_error"] == "http_500"