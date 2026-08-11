"""Provider-neutral LLM system adapter (OpenAI-compatible chat API).

Reads credentials from environment variables only:

- ``VICA_LLM_API_KEY`` (falls back to ``OPENAI_API_KEY``)
- ``VICA_LLM_BASE_URL``    (default ``https://api.openai.com/v1``)
- ``VICA_LLM_MODEL``       (required to run)
- ``VICA_LLM_TIMEOUT_SECONDS`` (default 60)
- ``VICA_LLM_MAX_RETRIES``     (default 1)
- ``VICA_LLM_INPUT_PRICE_PER_MTOK`` / ``VICA_LLM_OUTPUT_PRICE_PER_MTOK``
  (optional; used to estimate ``estimated_cost_usd``)

Network calls are isolated in this adapter. The candidate produced here is
validated exclusively by the deterministic VICA verifier.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from vica.protocol.models import SolveOutput

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_RETRIES = 1
_DEFAULT_TEMPERATURE = 0.0

# Allow overriding the HTTP transport (used by tests); not public API.
HttpPost = Callable[[str, dict[str, Any], dict[str, str], float], tuple[int, str]]

# Stable LLM outcome semantics (SPEC "LLM transport error semantics"):
#   success          — HTTP 200 and the response body parsed into a candidate
#   timeout          — explicit timeout (client socket timeout or HTTP 408/429/504)
#   transport_error  — network-level failure (DNS, connection refused, ...)
#   provider_error   — HTTP error status other than the timeout family
#   parse_error      — HTTP 200 but the body could not be parsed into a candidate
#   no_candidate     — nothing above produced a candidate
LLM_STATUSES = (
    "success",
    "timeout",
    "transport_error",
    "provider_error",
    "parse_error",
    "no_candidate",
)
LLM_TIMEOUT_HTTP = (408, 429, 504)


def classify_transport_status(status: int, text: str) -> str:
    """Map an HTTP transport outcome to one of the stable LLM statuses."""
    if status == 200:
        return "success"
    if status in LLM_TIMEOUT_HTTP:
        return "timeout"
    if status == 0:
        return "timeout" if "timeout" in text.lower() else "transport_error"
    return "provider_error"


class LLMSolverSystem:
    """OpenAI-compatible LLM participant for any ChallengeFamily."""

    system_id = "llm"
    supported_challenge_types: frozenset[str] = frozenset({"csp-v0.1"})

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        input_price_per_mtok: float | None = None,
        output_price_per_mtok: float | None = None,
    ) -> None:
        self.model = model or os.environ.get("VICA_LLM_MODEL", "") or ""
        if not self.model:
            raise ValueError(
                "LLMSolverSystem requires a model via VICA_LLM_MODEL or the "
                "'model' argument"
            )
        self.base_url = (
            base_url or os.environ.get("VICA_LLM_BASE_URL") or _DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key or os.environ.get("VICA_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        )
        self.timeout_seconds = _resolve_timeout_seconds(timeout_seconds)
        self.max_retries = _resolve_max_retries(max_retries)
        self.input_price_per_mtok = (
            input_price_per_mtok
            if input_price_per_mtok is not None
            else _env_float("VICA_LLM_INPUT_PRICE_PER_MTOK")
        )
        self.output_price_per_mtok = (
            output_price_per_mtok
            if output_price_per_mtok is not None
            else _env_float("VICA_LLM_OUTPUT_PRICE_PER_MTOK")
        )

    def config(self) -> dict[str, Any]:
        """Non-secret LLM configuration for reproducibility (never the API key)."""
        return {
            "provider": "openai-compatible",
            "model": self.model,
            "base_url": self.base_url,
            "temperature": _DEFAULT_TEMPERATURE,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "input_price_per_mtok": self.input_price_per_mtok,
            "output_price_per_mtok": self.output_price_per_mtok,
        }

    # ------------------------------------------------------------------ solve

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        if not self.api_key:
            raise RuntimeError(
                "LLMSolverSystem: no API key configured; set VICA_LLM_API_KEY "
                "or OPENAI_API_KEY"
            )

        payload: dict[str, Any] = challenge.get("payload", {})
        prompt = build_csp_prompt(payload)

        input_tokens = 0
        output_tokens = 0
        attempts = 0
        last_error: str | None = None
        transport_status = "no_candidate"
        start = time.perf_counter()

        candidate: Any = None
        for _ in range(self.max_retries + 1):
            attempts += 1
            status, text = _chat_completion(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                prompt=prompt,
                timeout_seconds=self.timeout_seconds,
            )
            transport_status = classify_transport_status(status, text)
            if transport_status != "success":
                last_error = f"http_{status}" if status else text.split(":", 1)[-1]
                continue
            try:
                data = json.loads(text)
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                input_tokens = int(usage.get("prompt_tokens", 0))
                output_tokens = int(usage.get("completion_tokens", 0))
                candidate = parse_candidate_json(content)
                transport_status = "success"
                break
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = f"parse:{type(exc).__name__}"
                transport_status = "parse_error"

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metadata = {
            "strategy": "llm-direct",
            "attempts": attempts,
            "model": self.model,
            "provider": "openai-compatible",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": _estimate_cost_usd(
                input_tokens, output_tokens, self.input_price_per_mtok, self.output_price_per_mtok
            ),
            "solve_wall_time_ms": elapsed_ms,
            "last_error": last_error or None,
            "status": transport_status,
        }
        return SolveOutput(candidate=candidate, metadata=metadata)


# --------------------------------------------------------------------- prompt


def build_csp_prompt(payload: dict[str, Any]) -> str:
    """Render a CSP-v0.1 payload as a human/LLM-readable problem statement."""
    try:
        variables: list[str] = list(payload["variables"])
        min_v = int(payload["min_value"])
        max_v = int(payload["max_value"])
        constraints = list(payload["constraints"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("payload is not a csp-v0.1 payload") from None

    lines = [
        "Solve the variable assignment problem below.",
        "",
        f"Variables: {', '.join(variables)}",
        f"Each variable Xi is an integer in [{min_v}, {max_v}] (inclusive).",
        "",
        "Constraints (all must hold):",
    ]
    for i, c in enumerate(constraints, start=1):
        lines.append(f"  {i}. {_render_constraint(c)}")
    lines += [
        "",
        'Respond with ONLY a JSON object with one key per variable, no extra text. '
        'Example: {"A0": 5, "A1": 12}',
    ]
    return "\n".join(lines)


def _render_constraint(c: dict[str, Any]) -> str:
    op = c["op"]
    vs = ", ".join(str(v) for v in c["vars"])
    if op == "eq":
        return f"{vs} are all equal"
    if op == "ne":
        return f"{vs} are all different from each other (pairwise unequal)"
    if op == "lt":
        return f"value({c['vars'][0]}) < value({c['vars'][1]})"
    if op == "add":
        return f"value({c['vars'][0]}) + value({c['vars'][1]}) = {c['target']}"
    if op == "xor":
        return f"value({c['vars'][0]}) XOR value({c['vars'][1]}) = {c['target']}"
    if op == "mod_sum":
        mod = c.get("mod", 31)
        terms = " + ".join(f"value({v})" for v in c["vars"])
        return f"({terms}) mod {mod} = {c['target']}"
    if op == "linear":
        terms = " + ".join(
            f"{coef}*value({v})" for coef, v in zip(c["coeffs"], c["vars"], strict=True)
        )
        return f"{terms} = {c['target']}"
    if op == "all_diff":
        return f"values {vs} are all distinct"
    return f"{op}({vs})"


# ------------------------------------------------------------------ synth prompt


def build_synth_prompt(payload: dict[str, Any]) -> str:
    """Render a SYNTH-v0.1 payload as an LLM-readable program-synthesis prompt.

    The task is to write a pure integer expression (DSL) that reproduces every
    public (input -> output) example. The DSL is deliberately small:
    operators ``+ - * % //``, ``min``/``max``, unary ``abs``/``neg``, integer
    literals, and the named variables.
    """
    try:
        fn_name = str(payload["function"]["name"])
        params = list(payload["function"]["params"])
        public_tests = list(payload["public_tests"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("payload is not a synth-v0.1 payload") from None

    lines = [
        "Write a pure integer expression that matches every input->output example.",
        "",
        f"Define a function named {fn_name} with parameter(s): {', '.join(params)}.",
        "",
        "Allowed expression language (no if/loops/assignment):",
        "  - integer literals (e.g. 3, -12)",
        "  - the variables: " + ", ".join(params),
        "  - binary operators: + - * % //",
        "  - min(a, b), max(a, b)",
        "  - unary: abs(x), and unary minus -x",
        "",
        "Examples (input -> expected output):",
    ]
    for t in public_tests:
        inp = ", ".join(f"{k}={v}" for k, v in t["input"].items())
        lines.append(f"  f({inp}) -> {t['expected']}")
    lines += [
        "",
        "Respond with ONLY a single expression (no code fence, no explanation), "
        "e.g.:  x * 2 + 3",
    ]
    return "\n".join(lines)


def parse_synth_candidate(raw: str) -> str | None:
    """Extract a single DSL expression string from an LLM response body.

    Tolerates markdown fences and trailing prose; returns None on failure.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:dsl|text)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Strip a leading "f(...) =" or "f(x) =" if the model echoed the signature.
    text = re.sub(r"^[A-Za-z_]\w*\s*\([^)]*\)\s*=\s*", "", text)
    # Drop natural-language prose that precedes the expression (DSL has no colon).
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    text = text.strip().strip("`").strip()
    if not text:
        return None
    return text


# ------------------------------------------------------------------- parsing


def parse_candidate_json(raw: str) -> Any:
    """Extract the JSON object from an LLM response body.

    Tolerates markdown fences and trailing prose, returns None on failure.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty response")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in response")
    obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON payload is not an object")
    return obj


# ------------------------------------------------------------------- transport


def _env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _resolve_timeout_seconds(timeout_seconds: float | None) -> float:
    """Explicit *timeout_seconds* wins over the environment default.

    ``is not None`` (never truthiness): an explicit 0 would otherwise silently
    fall back to the environment default.
    """
    resolved = (
        timeout_seconds
        if timeout_seconds is not None
        else float(os.environ.get("VICA_LLM_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
    )
    if resolved <= 0:
        raise ValueError("timeout_seconds must be > 0")
    return resolved


def _resolve_max_retries(max_retries: int | None) -> int:
    """Explicit *max_retries* wins over the environment default.

    ``is not None`` (never truthiness): ``max_retries=0`` must mean "zero
    retries", not "use the default".
    """
    resolved = (
        max_retries
        if max_retries is not None
        else int(os.environ.get("VICA_LLM_MAX_RETRIES", _DEFAULT_MAX_RETRIES))
    )
    if resolved < 0:
        raise ValueError("max_retries must be >= 0")
    return resolved


def _estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    input_price_per_mtok: float | None,
    output_price_per_mtok: float | None,
) -> float | None:
    """Estimate API cost in USD, or ``None`` when pricing is not configured.

    ``None`` means UNKNOWN / NOT MEASURED — it must never be rendered as $0. A
    genuine $0 is only reported when both prices are configured and no tokens
    were exchanged. See docs/SPEC.md "Cost semantics".
    """
    if input_price_per_mtok is None or output_price_per_mtok is None:
        return None
    return (input_tokens / 1e6) * input_price_per_mtok + (
        output_tokens / 1e6
    ) * output_price_per_mtok


def _chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout_seconds: float,
    system_content: str = "You are a precise problem solver. Always output valid JSON.",
    json_mode: bool = True,
) -> tuple[int, str]:
    url = f"{base_url}/chat/completions"
    payload_body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ],
        "temperature": _DEFAULT_TEMPERATURE,
    }
    if json_mode:
        payload_body["response_format"] = {"type": "json_object"}
    body = json.dumps(payload_body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        # Explicit client-side timeout — classified as `timeout`, not a generic
        # transport error; the runner must not record it as a wrong answer.
        return 0, f"network_error: timeout: {type(exc).__name__}"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return 0, "network_error: timeout"
        return 0, f"network_error: {exc.reason!r}"
    except OSError as exc:
        return 0, f"network_error: {type(exc).__name__}: {exc}"


# ------------------------------------------------------------------ synth LLM systems


class SynthLLMOneShotSystem:
    """LLM program-synthesis participant: a single-shot expression guess.

    Feeds the public examples to the LLM, asks for one DSL expression, and
    submits it. The verifier is the sole authority on correctness. This is the
    ``llm-one-shot`` baseline from the SYNTH design doc.
    """

    system_id = "llm-one-shot"
    supported_challenge_types: frozenset[str] = frozenset({"synth-v0.1"})

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        input_price_per_mtok: float | None = None,
        output_price_per_mtok: float | None = None,
    ) -> None:
        self.model = model or os.environ.get("VICA_LLM_MODEL", "") or ""
        if not self.model:
            raise ValueError(
                "SynthLLMOneShotSystem requires a model via VICA_LLM_MODEL or the "
                "'model' argument"
            )
        self.base_url = (
            base_url or os.environ.get("VICA_LLM_BASE_URL") or _DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key or os.environ.get("VICA_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        )
        self.timeout_seconds = _resolve_timeout_seconds(timeout_seconds)
        self.max_retries = _resolve_max_retries(max_retries)
        self.input_price_per_mtok = (
            input_price_per_mtok
            if input_price_per_mtok is not None
            else _env_float("VICA_LLM_INPUT_PRICE_PER_MTOK")
        )
        self.output_price_per_mtok = (
            output_price_per_mtok
            if output_price_per_mtok is not None
            else _env_float("VICA_LLM_OUTPUT_PRICE_PER_MTOK")
        )

    def config(self) -> dict[str, Any]:
        """Non-secret LLM configuration for reproducibility (never the API key)."""
        return {
            "provider": "openai-compatible",
            "model": self.model,
            "base_url": self.base_url,
            "temperature": _DEFAULT_TEMPERATURE,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "input_price_per_mtok": self.input_price_per_mtok,
            "output_price_per_mtok": self.output_price_per_mtok,
        }

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        if not self.api_key:
            raise RuntimeError(
                "SynthLLMOneShotSystem: no API key configured; set VICA_LLM_API_KEY "
                "or OPENAI_API_KEY"
            )
        payload = challenge.get("payload", {})
        prompt = build_synth_prompt(payload)

        input_tokens = 0
        output_tokens = 0
        attempts = 0
        last_error: str | None = None
        transport_status = "no_candidate"
        start = time.perf_counter()
        program: str | None = None
        for _ in range(self.max_retries + 1):
            attempts += 1
            status, text = _chat_completion(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                prompt=prompt,
                timeout_seconds=self.timeout_seconds,
                system_content="You are a precise program synthesizer. "
                    "Output only an expression.",
                json_mode=False,
            )
            transport_status = classify_transport_status(status, text)
            if transport_status != "success":
                last_error = f"http_{status}" if status else text.split(":", 1)[-1]
                continue
            try:
                data = json.loads(text)
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                input_tokens = int(usage.get("prompt_tokens", 0))
                output_tokens = int(usage.get("completion_tokens", 0))
                program = parse_synth_candidate(content)
                if program:
                    transport_status = "success"
                    last_error = None
                    break
                last_error = "parse:empty"
                transport_status = "parse_error"
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = f"parse:{type(exc).__name__}"
                transport_status = "parse_error"

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metadata = {
            "strategy": "llm-one-shot",
            "attempts": attempts,
            "model": self.model,
            "provider": "openai-compatible",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": _estimate_cost_usd(
                input_tokens, output_tokens, self.input_price_per_mtok, self.output_price_per_mtok
            ),
            "solve_wall_time_ms": elapsed_ms,
            "last_error": last_error or None,
            "status": transport_status,
        }
        candidate = {"program": program} if program else None
        return SolveOutput(candidate=candidate, metadata=metadata)


class SynthLLMAgentSystem:
    """LLM agent program-synthesis: generate, self-check on public tests,
    feed back failures, retry.

    Runs at most ``max_rounds`` iterations. Each round the LLM proposes an
    expression; the agent evaluates it against the public tests locally (via
    the family's cheap public-tests helper) purely as a self-check and returns
    the failing example to the LLM as feedback. The arena verifier remains the
    sole authority. This is the ``llm-agent`` baseline.
    """

    system_id = "llm-agent"
    supported_challenge_types: frozenset[str] = frozenset({"synth-v0.1"})

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        max_rounds: int = 5,
        input_price_per_mtok: float | None = None,
        output_price_per_mtok: float | None = None,
    ) -> None:
        self.model = model or os.environ.get("VICA_LLM_MODEL", "") or ""
        if not self.model:
            raise ValueError(
                "SynthLLMAgentSystem requires a model via VICA_LLM_MODEL or the "
                "'model' argument"
            )
        self.base_url = (
            base_url or os.environ.get("VICA_LLM_BASE_URL") or _DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key or os.environ.get("VICA_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        )
        self.timeout_seconds = _resolve_timeout_seconds(timeout_seconds)
        self.max_retries = _resolve_max_retries(max_retries)
        self.max_rounds = max_rounds
        self.input_price_per_mtok = (
            input_price_per_mtok
            if input_price_per_mtok is not None
            else _env_float("VICA_LLM_INPUT_PRICE_PER_MTOK")
        )
        self.output_price_per_mtok = (
            output_price_per_mtok
            if output_price_per_mtok is not None
            else _env_float("VICA_LLM_OUTPUT_PRICE_PER_MTOK")
        )

    def config(self) -> dict[str, Any]:
        """Non-secret LLM configuration for reproducibility (never the API key)."""
        return {
            "provider": "openai-compatible",
            "model": self.model,
            "base_url": self.base_url,
            "temperature": _DEFAULT_TEMPERATURE,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "max_rounds": self.max_rounds,
            "input_price_per_mtok": self.input_price_per_mtok,
            "output_price_per_mtok": self.output_price_per_mtok,
        }

    def solve(self, challenge: dict[str, Any]) -> SolveOutput:
        if not self.api_key:
            raise RuntimeError(
                "SynthLLMAgentSystem: no API key configured; set VICA_LLM_API_KEY "
                "or OPENAI_API_KEY"
            )
        payload = challenge.get("payload", {})
        from vica.challenges.synth_v01.family import public_tests_ok

        input_tokens = 0
        output_tokens = 0
        attempts = 0
        last_error: str | None = None
        transport_status = "no_candidate"
        completed_rounds = 0
        start = time.perf_counter()
        program: str | None = None

        prompt = build_synth_prompt(payload)
        feedback: str | None = None
        for _ in range(self.max_rounds):
            completed_rounds += 1
            round_prompt = (
                prompt if not feedback else f"{prompt}\n\nYour last answer failed.\n{feedback}"
            )
            for _ in range(self.max_retries + 1):
                attempts += 1
                status, text = _chat_completion(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    model=self.model,
                    prompt=round_prompt,
                    timeout_seconds=self.timeout_seconds,
                    system_content="You are a precise program synthesizer. "
                    "Output only an expression.",
                    json_mode=False,
                )
                transport_status = classify_transport_status(status, text)
                if transport_status != "success":
                    last_error = f"http_{status}" if status else text.split(":", 1)[-1]
                    continue
                try:
                    data = json.loads(text)
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage") or {}
                    input_tokens += int(usage.get("prompt_tokens", 0))
                    output_tokens += int(usage.get("completion_tokens", 0))
                    candidate_prog = parse_synth_candidate(content)
                    if not candidate_prog:
                        last_error = "parse:empty"
                        transport_status = "parse_error"
                        continue
                    if public_tests_ok(payload, candidate_prog):
                        program = candidate_prog
                        transport_status = "success"
                        last_error = None
                        break
                    # Self-check failed: build feedback from first failing example.
                    feedback = _first_failure(payload, candidate_prog)
                    transport_status = "parse_error"
                    last_error = None
                    break
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    last_error = f"parse:{type(exc).__name__}"
                    transport_status = "parse_error"
            if program is not None:
                break

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metadata = {
            "strategy": "llm-agent",
            "attempts": attempts,
            "rounds": completed_rounds,
            "model": self.model,
            "provider": "openai-compatible",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": _estimate_cost_usd(
                input_tokens, output_tokens, self.input_price_per_mtok, self.output_price_per_mtok
            ),
            "solve_wall_time_ms": elapsed_ms,
            "last_error": last_error or None,
            "status": transport_status,
        }
        candidate = {"program": program} if program else None
        return SolveOutput(candidate=candidate, metadata=metadata)


def _first_failure(payload: dict[str, Any], src: str) -> str:
    """Return a human-readable feedback string for the first failing public test."""
    from vica.challenges.synth_v01.family import eval_program, parse_program

    try:
        node = parse_program(src)
    except Exception as exc:
        return f"Your expression is not valid: {exc}"
    for t in payload.get("public_tests", []):
        try:
            got = eval_program(node, dict(t["input"]))
        except Exception as exc:
            inp = ", ".join(f"{k}={v}" for k, v in t["input"].items())
            return f"f({inp}) raised an error: {exc}"
        if got != t["expected"]:
            inp = ", ".join(f"{k}={v}" for k, v in t["input"].items())
            return f"f({inp}) -> {got}, expected {t['expected']}"
    return "Your expression passed all public tests."


__all__ = [
    "LLMSolverSystem",
    "SynthLLMAgentSystem",
    "SynthLLMOneShotSystem",
    "build_csp_prompt",
    "build_synth_prompt",
    "classify_transport_status",
    "parse_candidate_json",
    "parse_synth_candidate",
    "_chat_completion",
    "_estimate_cost_usd",
]