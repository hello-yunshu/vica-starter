"""SYNTH-v0.1 — program synthesis challenge family.

Design: docs/reports/synth-v0.1-design.md (design review passed).

The candidate is a program in a pure integer expression DSL (no eval,
no loops, no side effects):

    expr  := term | expr '+' term | expr '-' term
    term  := factor | term '*' factor | term '%' factor | term '//' factor
    factor:= INT | var | '(' expr ')' | '-' factor
           | min(expr, expr) | max(expr, expr) | abs(expr)

A challenge gives a function signature, 10 public (input -> output) examples,
and a budget. The reference target program and the hidden tests are both
secret-bound: they are regenerated at evaluation time from
(verifier_secret, seed, difficulty) and are never distributed. Public test
*inputs* come from the public (seed, difficulty); the *expected outputs* are
attached only by the verifier authority, because computing them requires the
secret-bound target. Without the secret, neither the target program nor the
hidden tests are derivable from the public material (docs/SPEC.md
"Verifier material").

Sandboxing for v0.1 is interpreter-level (no exec anywhere):
- program length / token count caps
- parse nesting depth cap
- per-op integer bit-length cap (kills bignum bombs)
- eager evaluation step cap
All caps are deterministic and map to SANDBOX_ERROR.
"""

from __future__ import annotations

import hashlib
import hmac
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from vica.protocol.models import ErrorCode
from vica.protocol.serialization import stable_hash
from vica.verifier.interfaces import EvaluationResult
from vica.verifier.material import verifier_material_commitment

TYPE_NAME = "synth-v0.1"
# Post-isolation generator semantics (target secret-bound, hidden secret-bound,
# public expected values secret-dependent) are NOT the historical 0.1.0
# generator (target derived from the public seed). 0.2.0 keeps provenance
# distinct: historical experiments remain labelled 0.1.0.
GENERATOR_VERSION = "0.2.0"

# Verifier-only secret key injected into the challenge dict by the authoritative
# verifier (verify_submission). Solver-facing challenge dicts never carry it, so
# a solver cannot regenerate hidden tests. See docs/SPEC.md "Verifier material".
VERIFIER_SECRET_KEY = "_verifier_secret"

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
    # Difficulty calibration (d4+): reject targets that are effectively
    # constant (trivial) or too small to pose a real search problem.
    min_nodes: int = 0
    reject_constant: bool = False


DIFFICULTY_PRESETS: dict[int, Preset] = {
    1: Preset(("+", "-"), (), 2, 20),
    2: Preset(("+", "-", "*", "%"), (), 3, 20),
    3: Preset(("+", "-", "*", "%", "//", "min", "max"), (), 4, 20),
    # d4/d5 calibrated: `abs` broadens the operator pool and inflates the share
    # of small/constant targets, which made brute-force success rebound above
    # d3. Enforcing a minimum target complexity (min_nodes) plus rejecting
    # constant functions restores strict monotonic difficulty (see
    # docs/reports/synth-v0.1-scale.md calibration section).
    4: Preset(
        ("+", "-", "*", "%", "//", "min", "max"),
        ("abs",),
        5,
        20,
        min_nodes=5,
        reject_constant=True,
    ),
    5: Preset(
        ("+", "-", "*", "%", "//", "min", "max"),
        ("abs", "neg"),
        6,
        20,
        min_nodes=7,
        reject_constant=True,
    ),
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


def _node_count(node: tuple[Any, ...]) -> int:
    """Number of AST nodes; used to enforce minimum target complexity."""
    kind = node[0]
    if kind in ("num", "var"):
        return 1
    if kind in ("neg", "abs"):
        return 1 + _node_count(node[1])
    return 1 + _node_count(node[1]) + _node_count(node[2])


def _is_effectively_constant(
    target: tuple[Any, ...], params: list[str], rng: random.Random, width: int
) -> bool:
    """True if the target yields the same value on several random inputs.

    Used to reject trivial constant targets (e.g. ``0 * 13`` or ``abs(15)``)
    that would be solvable by copying a single output and carry no reasoning.
    """
    outputs: set[int] = set()
    for _ in range(16):
        inp = {p: rng.randint(-width, width) for p in params}
        try:
            outputs.add(eval_program(target, inp))
        except (EvalError, SandboxLimit):
            return False
        if len(outputs) > 1:
            return False
    return True


def _errors_on_public_inputs(
    target: tuple[Any, ...], seed: str, difficulty: int
) -> bool:
    """True if the target raises on any public test input (div/mod by zero).

    Public example outputs are computed from the target by the verifier
    authority (``generate_with_solution``), and the public test inputs come
    from the public RNG — a target that cannot evaluate on one of them would
    make the challenge unassemblable. Such targets are rejected at sampling
    time, so ``generate(seed, difficulty)``'s public inputs and the
    authoritative payload's public tests are always the same vectors.
    """
    public = _public_payload(seed, difficulty)
    for case in public["public_test_inputs"]:
        try:
            eval_program(target, dict(case["input"]))
        except (EvalError, SandboxLimit):
            return True
    return False


# ------------------------------------------------------------------ generation

def _make_rng(seed: str, difficulty: int) -> random.Random:
    """Deterministic PRNG for solver-visible public material (test inputs).

    Keyed only by the public (seed, difficulty). It never samples the
    reference target, so knowing this RNG cannot recover the target program.
    """
    return random.Random(f"{TYPE_NAME}:{GENERATOR_VERSION}:public:{seed}:{difficulty}")


def _secret_rng(verifier_secret: str, tag: str, seed: str, difficulty: int) -> random.Random:
    """Deterministic PRNG keyed by the verifier secret with a domain tag.

    ``target_seed = HMAC-SHA256(verifier_secret, type:version:target:seed:difficulty)``
    ``hidden_seed = HMAC-SHA256(verifier_secret, type:version:hidden:seed:difficulty)``

    The ``target`` and ``hidden`` tags domain-separate the two streams: even
    with the same secret, target material and hidden-test material never share
    an RNG stream. Knowing only the public (seed, difficulty) — without the
    secret — cannot reconstruct either stream.
    """
    tag_bytes = f"{TYPE_NAME}:{GENERATOR_VERSION}:{tag}:{seed}:{difficulty}".encode()
    digest = hmac.new(verifier_secret.encode("utf-8"), tag_bytes, hashlib.sha256).hexdigest()
    return random.Random(digest)


def _target_rng(verifier_secret: str, seed: str, difficulty: int) -> random.Random:
    """RNG for the reference target program (verifier-only)."""
    return _secret_rng(verifier_secret, "target", seed, difficulty)


def _hidden_rng(verifier_secret: str, seed: str, difficulty: int) -> random.Random:
    """RNG for hidden test inputs (verifier-only).

    Domain-separated from the target stream via the ``hidden`` tag.
    """
    return _secret_rng(verifier_secret, "hidden", seed, difficulty)


@lru_cache(maxsize=4096)
def _generate_target(
    verifier_secret: str, seed: str, difficulty: int,
) -> tuple[tuple[Any, ...], str]:
    """Verifier-only reference target generation -> (target_ast, target_src).

    The target is sampled from a PRNG derived from the verifier secret, so the
    public (seed, difficulty) alone can never recover it. This is the core of
    the Research-Integrity boundary: a Coding Agent that can read this source
    still cannot regenerate the reference program without the secret.
    """
    try:
        preset = DIFFICULTY_PRESETS[difficulty]
    except KeyError:
        raise ValueError(
            f"unsupported difficulty {difficulty}; supported: {sorted(DIFFICULTY_PRESETS)}"
        ) from None

    rng = _target_rng(verifier_secret, seed, difficulty)
    params = list(_PARAM_POOL[difficulty])

    for _ in range(50):
        candidate_target = sample_program(
            rng, params, preset.ops, preset.unary, preset.max_depth, preset.input_width
        )
        # Reject trivial targets (bare var/num): no operation means the
        # challenge has no reasoning content and is solvable by copy.
        if candidate_target[0] in ("num", "var"):
            continue
        # Reject targets that cannot evaluate on the fixed public test inputs
        # (e.g. ``x // y`` with a zero divisor): the public examples would be
        # unassemblable by the verifier authority.
        if _errors_on_public_inputs(candidate_target, seed, difficulty):
            continue
        # Difficulty calibration filters (d4+): drop effectively-constant and
        # too-small targets so difficulty stays strictly monotonic.
        if preset.min_nodes and _node_count(candidate_target) < preset.min_nodes:
            continue
        if preset.reject_constant and _is_effectively_constant(
            candidate_target, params, rng, preset.input_width
        ):
            continue
        return candidate_target, program_to_source(candidate_target)
    raise RuntimeError("synth-v0.1: could not generate a well-formed target")


@lru_cache(maxsize=4096)
def _public_payload(seed: str, difficulty: int) -> dict[str, Any]:
    """Public-generation core -> solver-visible metadata + public test inputs.

    Only the public (seed, difficulty) is consumed: function signature,
    budget, input domain, and the public test *input* vectors. The expected
    outputs are attached by the verifier authority (``generate_with_solution``)
    because computing them requires the secret-bound reference target.
    """
    try:
        preset = DIFFICULTY_PRESETS[difficulty]
    except KeyError:
        raise ValueError(
            f"unsupported difficulty {difficulty}; supported: {sorted(DIFFICULTY_PRESETS)}"
        ) from None

    rng = _make_rng(seed, difficulty)
    params = list(_PARAM_POOL[difficulty])
    public_inputs = [
        {"input": {p: rng.randint(-preset.input_width, preset.input_width) for p in params}}
        for _ in range(preset.public_tests)
    ]
    return {
        "function": {"name": "f", "params": params},
        "input_width": preset.input_width,
        "budget": {"code_size": preset.code_size, "max_eval_ms": 10},
        "public_test_inputs": public_inputs,
    }


def generate(seed: str, difficulty: int) -> dict[str, Any]:
    """Public payload for (seed, difficulty).

    Contains the solver-visible metadata and the public test *inputs* only.
    It never contains the target program, hidden tests, or expected outputs
    — those require the verifier secret (authoritative path:
    ``generate_with_solution`` / ``build_challenge(..., verifier_secret=...)``).
    """
    return dict(_public_payload(seed, difficulty))


@lru_cache(maxsize=4096)
def _hidden_tests(
    verifier_secret: str, seed: str, difficulty: int,
) -> list[dict[str, Any]]:
    """Hidden test vectors for (secret, seed, difficulty).

    Deterministic for a fixed secret; different secrets yield different
    vectors. Inputs come from the domain-separated ``hidden`` stream and the
    expected outputs from the secret-bound target. Used only by the
    authoritative verifier (and tests/calibration that hold an explicit
    secret).
    """
    target, _ = _generate_target(verifier_secret, seed, difficulty)
    preset = DIFFICULTY_PRESETS[difficulty]
    params = list(_PARAM_POOL[difficulty])
    hidden = _sample_tests(
        _hidden_rng(verifier_secret, seed, difficulty),
        params,
        preset,
        target,
        preset.hidden_tests,
    )
    if hidden is None:
        raise RuntimeError("synth-v0.1: could not generate hidden tests")
    return hidden


def hidden_tests_for(
    seed: str, difficulty: int, verifier_secret: str
) -> list[dict[str, Any]]:
    """Hidden test vectors (input, expected) — for tests/calibration only.

    Requires the verifier *secret*; a solver holding only the public challenge
    cannot call this to obtain hidden material.
    """
    return _hidden_tests(verifier_secret, seed, difficulty)


def generate_with_solution(
    seed: str, difficulty: int, verifier_secret: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authoritative generation: full solver-visible payload + verifier solution.

    ``payload`` is the complete challenge payload — signature, budget, and the
    public (input -> expected) examples — assembled by the verifier authority
    from the secret-bound target. ``solution`` carries the reference target
    program and the hidden tests. Without ``verifier_secret`` neither is
    obtainable; the solution is never serialized into a public challenge.
    """
    payload = dict(_public_payload(seed, difficulty))
    target, target_src = _generate_target(verifier_secret, seed, difficulty)
    public_tests = []
    for case in payload.pop("public_test_inputs"):
        public_tests.append(
            {
                "input": dict(case["input"]),
                "expected": eval_program(target, dict(case["input"])),
            }
        )
    payload["public_tests"] = public_tests
    hidden = _hidden_tests(verifier_secret, seed, difficulty)
    return payload, {"target_program": target_src, "hidden_tests": hidden}


# ------------------------------------------------------------------ public helpers

def public_tests_ok(payload: dict[str, Any], src: str) -> bool:
    """Cheap self-check used by solver systems: does *src* match all public
    tests? Never raises. The arena verifier remains the authority.

    A payload without public examples (only the public-generation part) is
    not a solver-usable challenge and never passes this self-check.
    """
    public_tests = payload.get("public_tests")
    if not isinstance(public_tests, list) or not public_tests:
        return False
    try:
        node = parse_program(src)
        for t in public_tests:
            if eval_program(node, dict(t["input"])) != t["expected"]:
                return False
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ family

def _resolve_challenge(challenge: Any) -> tuple[dict[str, Any], str, int, str | None]:
    """Normalize a challenge into (payload, seed, difficulty, verifier_secret).

    The verifier secret is read from ``challenge[VERIFIER_SECRET_KEY]`` when the
    authoritative verifier injected it (``verify_submission``). Solver-facing
    challenge dicts never carry it, so only the authority can unlock hidden
    tests. When only a bare payload is given (tests / solver self-checks) a
    stable payload-derived seed is used and no hidden material is available.
    """
    if not isinstance(challenge, dict):
        raise TypeError("challenge must be a dict")
    secret = challenge.get(VERIFIER_SECRET_KEY)
    secret = str(secret) if isinstance(secret, str) and secret else None
    payload = challenge.get("payload")
    if isinstance(payload, dict):
        seed = challenge.get("seed")
        difficulty = challenge.get("difficulty")
        seed = str(seed) if seed not in (None, "") else f"{stable_hash(payload)}:payload"
        difficulty = int(difficulty) if difficulty is not None else 0
        if difficulty not in DIFFICULTY_PRESETS:
            difficulty = 1
        return payload, seed, difficulty, secret
    if "public_tests" in challenge:
        return challenge, f"{stable_hash(challenge)}:payload", 1, secret
    raise TypeError("not a synth-v0.1 payload")


class SynthV01:
    """SYNTH-v0.1 ChallengeFamily: DSL generator + deterministic verifier."""

    type_name = TYPE_NAME
    generator_version = GENERATOR_VERSION
    # This family's reference target is secret-bound: a complete, solver-usable
    # challenge (with public examples) can only be assembled by an authority
    # holding the verifier secret (registry.build_challenge).
    requires_verifier_secret = True

    def generate(self, seed: str, difficulty: int) -> dict[str, Any]:
        return generate(seed, difficulty)

    def generate_with_solution(
        self, seed: str, difficulty: int, verifier_secret: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Authoritative assembly (see module-level ``generate_with_solution``)."""
        return generate_with_solution(seed, difficulty, verifier_secret)

    def verify(self, challenge: Any, candidate: Any) -> bool:
        return self.evaluate(challenge, candidate).valid

    def score(self, challenge: Any, candidate: Any) -> float:
        return self.evaluate(challenge, candidate).score

    def evaluate(self, challenge: Any, candidate: Any) -> EvaluationResult:
        """Single authoritative pass: validity + score computed exactly once."""
        fail = self.failure_code(challenge, candidate)
        valid = fail is None
        return EvaluationResult(valid=valid, score=1.0 if valid else 0.0, error_code=fail)

    def failure_code(self, challenge: Any, candidate: Any) -> ErrorCode | None:
        try:
            payload, seed, difficulty, secret = _resolve_challenge(challenge)
            preset = DIFFICULTY_PRESETS[difficulty]
        except (TypeError, ValueError, KeyError):
            return ErrorCode.INVALID_SCHEMA

        if not isinstance(candidate, dict) or not isinstance(candidate.get("program"), str):
            return ErrorCode.INVALID_SCHEMA
        src = str(candidate["program"])

        # A solver-usable challenge must carry public examples. The public-only
        # generation output (signature/budget/inputs without expected values)
        # is not a verifiable challenge: expected outputs require the
        # secret-bound target, so only the authoritative path yields one.
        public_tests = payload.get("public_tests")
        if not isinstance(public_tests, list) or not public_tests:
            return ErrorCode.INVALID_SCHEMA

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

        for test in public_tests:
            code = self._test_code(node, test)
            if code is not None:
                return code
        # Verifier-material binding: when the challenge commits to a material
        # (``verifier_material_commitment`` on the Challenge), the supplied
        # secret must reproduce that commitment. A mismatch is an evaluator
        # configuration failure (INTERNAL_ERROR, reason
        # ``verifier_material_mismatch``), never a solver INVALID_SOLUTION, and
        # hidden tests are never evaluated with the wrong material.
        commitment = challenge.get("verifier_material_commitment")
        if secret is not None and commitment is not None:
            if verifier_material_commitment(secret) != commitment:
                return ErrorCode.INTERNAL_ERROR
        # Hidden material is only checked when the authoritative verifier
        # supplied its secret. Without it (solver self-check path) only the
        # public tests are authoritative — which is exactly the intended
        # boundary: solvers never see hidden material.
        if secret is not None:
            try:
                hidden = _hidden_tests(secret, seed, difficulty)
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
    "VERIFIER_SECRET_KEY",
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