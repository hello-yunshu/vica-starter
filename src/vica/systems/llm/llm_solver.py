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

# Allow overriding the HTTP transport (used by tests); not public API.
HttpPost = Callable[[str, dict[str, Any], dict[str, str], float], tuple[int, str]]


class LLMSolverSystem:
    """OpenAI-compatible LLM participant for any ChallengeFamily."""

    system_id = "llm"

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
        self.timeout_seconds = timeout_seconds or float(
            os.environ.get("VICA_LLM_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
        )
        self.max_retries = max_retries or int(
            os.environ.get("VICA_LLM_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
        )
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
        last_error = ""
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
            if status != 200:
                last_error = f"http_{status}"
                continue
            try:
                data = json.loads(text)
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                input_tokens = int(usage.get("prompt_tokens", 0))
                output_tokens = int(usage.get("completion_tokens", 0))
                candidate = parse_candidate_json(content)
                break
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = f"parse:{type(exc).__name__}"

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


def _estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    input_price_per_mtok: float | None,
    output_price_per_mtok: float | None,
) -> float:
    if input_price_per_mtok is None or output_price_per_mtok is None:
        return 0.0
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
) -> tuple[int, str]:
    url = f"{base_url}/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise problem solver. Always output valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
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
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f"network_error: {type(exc).__name__}"


__all__ = [
    "LLMSolverSystem",
    "build_csp_prompt",
    "parse_candidate_json",
    "_estimate_cost_usd",
]