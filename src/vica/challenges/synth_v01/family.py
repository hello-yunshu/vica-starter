"""SYNTH-v0.1 — program synthesis challenge family.

Design: docs/reports/synth-v0.1-design.md (design review passed).

The candidate is a program in a pure integer expression DSL (no eval,
no loops, no side effects):

    expr  := term | expr '+' term | expr '-' term
    term  := factor | term '*' factor | term '%' factor | term '//' factor
    factor:= INT | var | '(' expr ')' | '-' factor
           | min(expr, expr) | max(expr, expr) | abs(expr)

A challenge gives a function signature, 10 public (input -> output)
examples, and a budget. The verifier regenerates the hidden tests from
(seed, difficulty) at evaluation time — they are never distributed.

Sandboxing for v0.1 is interpreter-level (no exec anywhere):
- program length / token count caps
- parse nesting depth cap
- per-op integer bit-length cap (kills bignum bombs)
- eager evaluation step cap
All caps are deterministic and map to SANDBOX_ERROR.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from vica.protocol.models import ErrorCode
from vica.protocol.serialization import stable_hash

TYPE_NAME = "synth-v0.1"
GENERATOR_VERSION = "0.1.0"

# ------------------------------------------------------------------ sandbox

MAX_PROGRAM_CHARS = 1 << 20  # reject absurd strings before lexing
MAX_TOKENS = 4096  # hard cap; tone past the declared budget is a guard hit
MAX_PARSE_DEPTH = 96
MAX_EVAL_STEPS = 200_000
MAX_INT_BITS = 65536  # any intermediate/result above this is a sandbox hit

ALL_BINARY_OPS = ("+", "-", "*", "%", "//", "min", "max")
ALL_UNARY_OPS = ("abs", "neg")


class ParseError(ValueError):
    """The program text is not valid DSL."""


class EvalError(ValueError):
    """The program is valid DSL but cannot execute (div0, unknown var)."""


class SandboxLimit(RuntimeError):
    """A resource guard (depth/size/bits/steps) rejected the program."""


# ------------------------------------------------------------------ difficulty

@dataclass(frozen=True)
class Preset:
    ops: tuple[str, ...]
    unary: tuple[str, ...]
    max_depth: int
    input_width: int
    public_tests: int = 10
    hidden_tests: int = 40
    code_size: int = 200


DIFFICULTY_PRESETS: dict[int, Preset] = {
    1: Preset(("+", "-"), (), 2, 20),
    2: Preset(("+", "-", "*", "%"), (), 3, 20),
    3: Preset(("+", "-", "*", "%", "//", "min", "max"), (), 4, 20),
    4: Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs",), 5, 20),
    5: Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs", "neg"), 6, 20),
}

MAX_DIFFICULTY = max(DIFFICULTY_PRESETS)

# Function signature per difficulty: d1-2 single input, d3-4 two, d5 three.
_PARAM_POOL: dict[int, tuple[str, ...]] = {
    1: ("x",),
    2: ("x",),
    3: ("x", "y"),
    4: ("x", "y"),
    5: ("x", "y", "z"),
}


# ------------------------------------------------------------------ lexer / parser

def _lex(src: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            tokens.append(("num", src[i:j]))
            i = j
        elif c.isalpha():
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            tokens.append(("ident", src[i:j]))
            i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            tokens.append(("//", "//"))
            i += 2
        elif c in "+-*%(),":
            tokens.append((c, c))
            i += 1
        else:
            raise ParseError(f"unexpected character {c!r} at offset {i}")
    return tokens


def token_count(src: str) -> int:
    """Number of DSL tokens in *src* (used for the code-size budget)."""
    return len(_lex(src))


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, str] | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def take(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of program")
        self.pos += 1
        return tok

    def expect(self, kind: str) -> tuple[str, str]:
        tok = self.take()
        if tok[0] != kind:
            raise ParseError(f"expected {kind!r}, got {tok[0]!r}")
        return tok

    def expr(self, depth: int = 0) -> tuple[Any, ...]:
        if depth > MAX_PARSE_DEPTH:
            raise SandboxLimit("parse nesting too deep")
        node = self.term(depth)
        while True:
            tok = self.peek()
            if tok is not None and tok[0] in ("+", "-"):
                self.take()
                node = (tok[0], node, self.term(depth))
            else:
                return node

    def term(self, depth: int = 0) -> tuple[Any, ...]:
        node = self.factor(depth)
        while True:
            tok = self.peek()
            if tok is not None and tok[0] in ("*", "%", "//"):
                self.take()
                node = (tok[0], node, self.factor(depth))
            else:
                return node

    def factor(self, depth: int = 0) -> tuple[Any, ...]:
        tok = self.take()
        kind, value = tok
        if kind == "num":
            return ("num", int(value))
        if kind == "ident":
            if value in ("min", "max", "abs"):
                self.expect("(")
                first = self.expr(depth + 1)
                if value == "abs":
                    self.expect(")")
                    return ("abs", first)
                self.expect(",")
                second = self.expr(depth + 1)
                self.expect(")")
                return (value, first, second)
            return ("var", value)
        if kind == "(":
            node = self.expr(depth + 1)
            self.expect(")")
            return node
        if kind == "-":
            return ("neg", self.factor(depth + 1))
        raise ParseError(f"unexpected token {kind!r}")


def parse_program(src: str) -> tuple[Any, ...]:
    """Parse DSL source into an AST tuple. Raises ParseError / SandboxLimit."""
    if not isinstance(src, str):
        raise ParseError("program must be a string")
    if len(src) > MAX_PROGRAM_CHARS:
        raise ParseError("program too long")
    tokens = _lex(src)
    if not tokens:
        raise ParseError("empty program")
    parser = _Parser(tokens)
    node = parser.expr()
    if parser.pos != len(tokens):
        raise ParseError(f"unexpected trailing tokens at offset {parser.pos}")
    return node


# ------------------------------------------------------------------ printing

_PRECEDENCE = {"+": 1, "-": 1, "*": 2, "%": 2, "//": 2}
# Unary / call precedences (higher than any binary op).
_NEG_PREC = 3
_CALL_PREC = 4


def program_to_source(node: tuple[Any, ...]) -> str:
    """Canonical infix printing of an AST (round-trips through the parser)."""

    def render(n: tuple[Any, ...], parent_prec: int = 0, right: bool = False) -> str:
        kind = n[0]
        if kind == "num":
            return str(n[1])
        if kind == "var":
            return n[1]
        if kind == "neg":
            # operand at _NEG_PREC: binary ops (prec 1/2) get wrapped; num/var/neg/abs do not.
            s = f"-{render(n[1], _NEG_PREC)}"
            if _NEG_PREC < parent_prec or (_NEG_PREC == parent_prec and right):
                return "(" + s + ")"
            return s
        if kind == "abs":
            s = f"abs({render(n[1], 0)})"
            if _CALL_PREC < parent_prec or (_CALL_PREC == parent_prec and right):
                return "(" + s + ")"
            return s
        if kind in ("min", "max"):
            return f"{kind}({render(n[1], 0)}, {render(n[2], 0)})"
        prec = _PRECEDENCE[kind]
        left = render(n[1], prec, False)
        right_s = render(n[2], prec, True)
        s = f"{left} {kind} {right_s}"
        if prec < parent_prec or (prec == parent_prec and right):
            return "(" + s + ")"
        return s

    return render(node)


# ------------------------------------------------------------------ evaluation

class _EvalState:
    __slots__ = ("steps",)

    def __init__(self) -> None:
        self.steps = 0


def eval_program(node: tuple[Any, ...], variables: dict[str, int]) -> int:
    """Evaluate an AST against integer variable bindings.

    Raises EvalError (div-by-zero, unknown variable) or SandboxLimit
    (bit-length / step guard).
    """
    return _eval(node, variables, _EvalState())


def _check_bits(value: int) -> None:
    if value.bit_length() > MAX_INT_BITS:
        raise SandboxLimit("integer too large")


def _eval(node: tuple[Any, ...], variables: dict[str, int], state: _EvalState) -> int:
    """Iterative post-order evaluation.

    A recursive evaluator would stack-overflow on adversarial wide/flat
    expressions (e.g. ``1 + 1 + ... + 1`` with many terms) before the step
    guard could fire. The explicit stack keeps evaluation bounded solely by
    the sandbox counters (steps / bit-length), never by the CPython call
    stack, so a malicious candidate cannot crash the process.
    """
    _BINARY = ("+", "-", "*", "%", "//", "min", "max")
    # Each stack entry: (node, visited). visited=False means "push children";
    # visited=True means "children already evaluated, combine now".
    stack: list[tuple[tuple[Any, ...], bool]] = [(node, False)]
    values: list[int] = []

    while stack:
        n, visited = stack.pop()
        state.steps += 1
        if state.steps > MAX_EVAL_STEPS:
            raise SandboxLimit("eval steps exceeded")
        kind = n[0]

        if kind == "num":
            values.append(n[1])
            continue
        if kind == "var":
            try:
                values.append(variables[n[1]])
            except KeyError:
                raise EvalError(f"unknown variable {n[1]!r}") from None
            continue
        if kind in ("neg", "abs"):
            if visited:
                v = values.pop()
                _check_bits(v)
                values.append(-v if kind == "neg" else abs(v))
            else:
                stack.append((n, True))
                stack.append((n[1], False))
            continue
        if kind in _BINARY:
            if visited:
                right = values.pop()
                left = values.pop()
                if kind == "+":
                    _check_bits(left)
                    _check_bits(right)
                    result = left + right
                elif kind == "-":
                    _check_bits(left)
                    _check_bits(right)
                    result = left - right
                elif kind == "*":
                    _check_bits(left)
                    _check_bits(right)
                    result = left * right
                elif kind == "%":
                    if right == 0:
                        raise EvalError("modulo by zero")
                    result = left % right
                elif kind == "//":
                    if right == 0:
                        raise EvalError("division by zero")
                    result = left // right
                elif kind == "min":
                    result = min(left, right)
                else:
                    result = max(left, right)
                _check_bits(result)
                values.append(result)
            else:
                # Push self (visited), then right, then left so that left is
                # processed first and ends up below right on the value stack.
                stack.append((n, True))
                stack.append((n[2], False))
                stack.append((n[1], False))
            continue
        raise EvalError(f"unknown node kind {kind!r}")

    return values[0]


# ------------------------------------------------------------------ sampling

def sample_program(
    rng: random.Random,
    params: list[str],
    ops: tuple[str, ...],
    unary: tuple[str, ...],
    max_depth: int,
    width: int,
) -> tuple[Any, ...]:
    """Random AST using *ops*/*unary* within *max_depth* (ramped)."""

    def leaf() -> tuple[Any, ...]:
        if rng.random() < 0.5:
            return ("var", rng.choice(params))
        return ("num", rng.randint(-width, width))

    def build(depth: int) -> tuple[Any, ...]:
        if depth <= 1:
            return leaf()
        roll = rng.random()
        if roll < 0.45:
            return leaf()
        if roll < 0.80:
            op = rng.choice(ops)
            if op == "neg":
                return ("neg", build(depth - 1))
            return (op, build(depth - 1), build(depth - 1))
        if unary and roll < 0.90:
            return (rng.choice(unary), build(depth - 1))
        op = rng.choice(ops) if ops else "+"
        if op == "neg":
            return ("neg", build(depth - 1))
        return (op, build(depth - 1), build(depth - 1))

    return build(max_depth)


def _sample_tests(
    rng: random.Random,
    params: list[str],
    preset: Preset,
    target: tuple[Any, ...],
    count: int,
) -> list[dict[str, Any]] | None:
    tests: list[dict[str, Any]] = []
    for _ in range(count):
        for _ in range(1000):
            inp = {p: rng.randint(-preset.input_width, preset.input_width) for p in params}
            try:
                expected = eval_program(target, inp)
            except (EvalError, SandboxLimit):
                continue
            tests.append({"input": inp, "expected": expected})
            break
        else:
            return None
    return tests


# ------------------------------------------------------------------ generation

def _make_rng(seed: str, difficulty: int) -> random.Random:
    return random.Random(f"{TYPE_NAME}:{GENERATOR_VERSION}:{seed}:{difficulty}")


@lru_cache(maxsize=4096)
def _generate_all(
    seed: str, difficulty: int,
) -> tuple[dict[str, Any], str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic generation core -> (payload, target_src, public, hidden).

    Cached: the verifier regenerates hidden tests for every submission, and
    generation is pure (seed, difficulty) -> tuple.
    """
    try:
        preset = DIFFICULTY_PRESETS[difficulty]
    except KeyError:
        raise ValueError(
            f"unsupported difficulty {difficulty}; supported: {sorted(DIFFICULTY_PRESETS)}"
        ) from None

    rng = _make_rng(seed, difficulty)
    params = list(_PARAM_POOL[difficulty])

    target: tuple[Any, ...] | None = None
    public: list[dict[str, Any]] | None = None
    hidden: list[dict[str, Any]] | None = None
    target_src = ""
    for _ in range(50):
        candidate_target = sample_program(
            rng, params, preset.ops, preset.unary, preset.max_depth, preset.input_width
        )
        # Reject trivial targets (bare var/num): no operation means the
        # challenge has no reasoning content and is solvable by copy.
        if candidate_target[0] in ("num", "var"):
            continue
        pub = _sample_tests(rng, params, preset, candidate_target, preset.public_tests)
        if pub is None:
            continue
        hid = _sample_tests(rng, params, preset, candidate_target, preset.hidden_tests)
        if hid is None:
            continue
        target = candidate_target
        public = pub
        hidden = hid
        target_src = program_to_source(candidate_target)
        break
    if target is None:
        raise RuntimeError("synth-v0.1: could not generate a well-formed challenge")
    assert public is not None and hidden is not None  # set together with target

    payload = {
        "function": {"name": "f", "params": params},
        "public_tests": public,
        "input_width": preset.input_width,
        "budget": {"code_size": preset.code_size, "max_eval_ms": 10},
    }
    return payload, target_src, public, hidden


def generate(seed: str, difficulty: int) -> dict[str, Any]:
    """Public payload for (seed, difficulty). Never contains the target or
    hidden tests."""
    payload, _, _, _ = _generate_all(seed, difficulty)
    return payload


def hidden_tests_for(seed: str, difficulty: int) -> list[dict[str, Any]]:
    """Hidden test vectors (input, expected) — for tests/calibration only."""
    _, _, _, hidden = _generate_all(seed, difficulty)
    return hidden


def generate_with_solution(seed: str, difficulty: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Payload plus the hidden solution reference (target program + hidden
    tests). The hidden solution is never serialized into a public challenge."""
    payload, target_src, _, hidden = _generate_all(seed, difficulty)
    return payload, {"target_program": target_src, "hidden_tests": hidden}


# ------------------------------------------------------------------ public helpers

def public_tests_ok(payload: dict[str, Any], src: str) -> bool:
    """Cheap self-check used by solver systems: does *src* match all public
    tests? Never raises. The arena verifier remains the authority."""
    try:
        node = parse_program(src)
        for t in payload.get("public_tests", []):
            if eval_program(node, dict(t["input"])) != t["expected"]:
                return False
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ family

def _resolve_challenge(challenge: Any) -> tuple[dict[str, Any], str, int]:
    """Normalize either a full challenge dict or a bare payload.

    Hidden-test regeneration needs (seed, difficulty). When only a bare
    payload is given (tests, ad-hoc calls) a stable payload-derived seed is
    used; the public tests are still checked against the given payload.
    """
    if not isinstance(challenge, dict):
        raise TypeError("challenge must be a dict")
    payload = challenge.get("payload")
    if isinstance(payload, dict):
        seed = challenge.get("seed")
        difficulty = challenge.get("difficulty")
        seed = str(seed) if seed not in (None, "") else f"{stable_hash(payload)}:payload"
        difficulty = int(difficulty) if difficulty is not None else 0
        if difficulty not in DIFFICULTY_PRESETS:
            difficulty = 1
        return payload, seed, difficulty
    if "public_tests" in challenge:
        return challenge, f"{stable_hash(challenge)}:payload", 1
    raise TypeError("not a synth-v0.1 payload")


class SynthV01:
    """SYNTH-v0.1 ChallengeFamily: DSL generator + deterministic verifier."""

    type_name = TYPE_NAME
    generator_version = GENERATOR_VERSION

    def generate(self, seed: str, difficulty: int) -> dict[str, Any]:
        return generate(seed, difficulty)

    def verify(self, challenge: Any, candidate: Any) -> bool:
        return self.failure_code(challenge, candidate) is None

    def score(self, challenge: Any, candidate: Any) -> float:
        return 1.0 if self.verify(challenge, candidate) else 0.0

    def failure_code(self, challenge: Any, candidate: Any) -> ErrorCode | None:
        try:
            payload, seed, difficulty = _resolve_challenge(challenge)
            preset = DIFFICULTY_PRESETS[difficulty]
        except (TypeError, ValueError, KeyError):
            return ErrorCode.INVALID_SCHEMA

        if not isinstance(candidate, dict) or not isinstance(candidate.get("program"), str):
            return ErrorCode.INVALID_SCHEMA
        src = str(candidate["program"])

        # code-size budget + hard guard
        try:
            size = token_count(src)
        except ParseError:
            return ErrorCode.INVALID_SCHEMA
        if size > preset.code_size:
            return ErrorCode.INVALID_SCHEMA
        if size > MAX_TOKENS:
            return ErrorCode.SANDBOX_ERROR

        try:
            node = parse_program(src)
        except SandboxLimit:
            return ErrorCode.SANDBOX_ERROR
        except ParseError:
            return ErrorCode.INVALID_SCHEMA

        for test in payload.get("public_tests", []):
            code = self._test_code(node, test)
            if code is not None:
                return code
        try:
            _, _, _, hidden = _generate_all(seed, difficulty)
        except (ValueError, RuntimeError):
            return ErrorCode.INTERNAL_ERROR
        for test in hidden:
            code = self._test_code(node, test)
            if code is not None:
                return code
        return None

    @staticmethod
    def _test_code(node: tuple[Any, ...], test: dict[str, Any]) -> ErrorCode | None:
        """INVALID_SCHEMA (cannot execute), SANDBOX_ERROR (guard hit),
        INVALID_SOLUTION (wrong output), or None (test passes)."""
        try:
            got = eval_program(node, dict(test["input"]))
        except SandboxLimit:
            return ErrorCode.SANDBOX_ERROR
        except EvalError:
            return ErrorCode.INVALID_SCHEMA
        except Exception:
            return ErrorCode.INVALID_SCHEMA
        if got != test["expected"]:
            return ErrorCode.INVALID_SOLUTION
        return None


FAMILY = SynthV01()

__all__ = [
    "ALL_BINARY_OPS",
    "ALL_UNARY_OPS",
    "DIFFICULTY_PRESETS",
    "EvalError",
    "FAMILY",
    "GENERATOR_VERSION",
    "MAX_DIFFICULTY",
    "MAX_INT_BITS",
    "MAX_PARSE_DEPTH",
    "MAX_TOKENS",
    "ParseError",
    "Preset",
    "SandboxLimit",
    "TYPE_NAME",
    "eval_program",
    "generate",
    "generate_with_solution",
    "hidden_tests_for",
    "parse_program",
    "program_to_source",
    "public_tests_ok",
    "sample_program",
    "token_count",
]