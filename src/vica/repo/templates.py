"""REPO-v0.1 task templates (generator 0.2.0).

Each template defines the *semantics* of one small Python task. A concrete
solver-visible **source instance** — buggy (workspace) source, reference
(fixed) source, task text, and a parameterized input sampler — is assembled by
``build_source_instance`` from a per-instance RNG. The generator feeds it a
verifier-secret-bound RNG, so a released challenge's reference implementation
is only derivable by an authority holding the verifier secret.

Leakage contract (v1.0.1 research-integrity hotfix):

- The public ``Template`` object exposes **no** fixed/reference source.
  ``TEMPLATES[name].fixed`` no longer exists; there is no
  ``reference_source`` / ``fixed_source`` / ``solution_source`` /
  ``correct_source`` / ``reference_patch`` / ``answer_patch`` attribute on any
  public object.
- The only path to a challenge's fixed source / reference patch is
  ``vica.repo.generator.generate_with_solution(..., verifier_secret)``.
- The instance RNG is domain-separated and secret-bound; reading the
  open-source builder cannot reproduce a released challenge's reference
  material without the secret (docs/SPEC.md "Verifier material").

Instance variation (not cosmetic noise): identifiers, helper-vs-inline
structure, constants (cache capacity, separators, state tokens), data layout,
and code organization all change with the instance RNG, so different seeds
produce genuinely different workspace source and generally different repair
patches — not just different hidden inputs.

Every template exposes exactly one entry point:

    solution.solve(*args) -> Any

The generator classifies inputs automatically:

- **public** cases are inputs on which ``buggy == fixed`` (a NoOp patch passes
  public tests — the honest hint);
- **hidden** cases are inputs on which ``buggy != fixed`` (a NoOp patch fails
  them — the discriminating negative control).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceInstance:
    """One concrete source instance (buggy + fixed + task + sampler).

    ``fixed`` is the authoritative reference implementation of the instance
    and must only be reached through the generator's secret-gated assembly
    path (never by solver-facing code).
    """

    template: str
    task_kind: str  # "repair" | "implementation"
    task: str
    buggy: str
    fixed: str
    sampler: Callable[[random.Random], tuple[Any, ...]]


@dataclass(frozen=True)
class Template:
    """Public template metadata. Intentionally carries NO fixed source."""

    name: str
    task_kind: str  # "repair" | "implementation"
    builder: Callable[[random.Random], SourceInstance]


def _run_source(src: str, args: tuple[Any, ...]) -> Any:
    """Execute a source string in an isolated namespace and call ``solve``."""
    ns: dict[str, Any] = {}
    exec(compile(src, "<template>", "exec"), ns)  # trusted template code
    return ns["solve"](*args)


# ------------------------------------------------------------------ classification

class _Missing:
    def __eq__(self, other: Any) -> bool:
        return False

    def __repr__(self) -> str:  # pragma: no cover
        return "<missing>"


_MISSING = _Missing()


def _classify_set(
    instance: SourceInstance,
    rng: random.Random,
    count: int,
    *,
    want_public: bool,
) -> list[dict[str, Any]]:
    """Collect *count* cases whose buggy/fixed relationship matches *want_public*.

    ``want_public=True`` collects inputs on which ``buggy == fixed`` (a NoOp
    patch passes them — the honest hint). ``want_public=False`` collects inputs
    on which ``buggy != fixed`` (a NoOp patch fails them — the discriminating
    negative control). The two sets are drawn from the *same* RNG stream passed
    in, so callers can domain-separate public vs hidden material by supplying
    different RNGs (see :mod:`vica.repo.generator`).
    """
    collected: list[dict[str, Any]] = []
    attempts = 0
    max_attempts = count * 200
    while len(collected) < count and attempts < max_attempts:
        attempts += 1
        args = instance.sampler(rng)
        try:
            expected = _run_source(instance.fixed, args)
        except Exception:
            continue
        try:
            buggy_out = _run_source(instance.buggy, args)
        except Exception:
            buggy_out = _MISSING
        if (buggy_out == expected) is want_public:
            collected.append({"args": list(args), "expected": expected})
    if len(collected) < count:
        raise RuntimeError(
            f"template {instance.template}: could not classify enough "
            f"{'public' if want_public else 'hidden'} cases "
            f"({len(collected)}/{count})"
        )
    return collected


def classify_public(
    instance: SourceInstance,
    rng: random.Random,
    *,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """Collect inputs on which the buggy and fixed sources agree (public tests)."""
    return _classify_set(instance, rng, count or 4, want_public=True)


def classify_hidden(
    instance: SourceInstance,
    rng: random.Random,
    *,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """Collect inputs on which the buggy and fixed sources disagree (hidden tests)."""
    return _classify_set(instance, rng, count or 8, want_public=False)


def _pick(rng: random.Random, a: str, b: str) -> str:
    return b if rng.random() < 0.5 else a


# ---------------------------------------------------------------------- parser

def _parser_sources(rng: random.Random) -> tuple[dict[str, str], bool]:
    names = {
        "result": _pick(rng, "result", "parsed"),
        "line": _pick(rng, "line", "row"),
        "key": _pick(rng, "key", "k"),
        "value": _pick(rng, "value", "v"),
        "split": _pick(rng, "_split", "_parse_pair"),
    }
    helper = rng.random() < 0.5
    return names, helper


def _render_parser(names: dict[str, str], helper: bool, keep_quotes: bool) -> str:
    q = '"'
    strip_quotes = (
        ""
        if keep_quotes
        else (
            f"        if len({names['value']}) >= 2 and "
            f"{names['value']}.startswith({q!r}) and {names['value']}.endswith({q!r}):\n"
            f"            {names['value']} = {names['value']}[1:-1]\n"
        )
    )
    if helper:
        helper_src = f'''


def {names["split"]}({names["line"]}: str) -> tuple[str, str] | None:
    """Split one key=value line; lines without '=' return None."""
    if "=" not in {names["line"]}:
        return None
    key, value = {names["line"]}.split("=", 1)
    return key.strip(), value.strip()
'''
        body = f"""    {names['result']}: dict[str, str] = {{}}
    for {names['line']} in text.splitlines():
        if not {names['line']}.strip():
            continue
        pair = {names['split']}({names['line']})
        if pair is None:
            continue
        {names['key']}, {names['value']} = pair
{strip_quotes}        {names['result']}[{names['key']}] = {names['value']}
    return {names['result']}"""
    else:
        helper_src = ""
        body = f"""    {names['result']}: dict[str, str] = {{}}
    for {names['line']} in text.splitlines():
        if not {names['line']}.strip():
            continue
        if "=" not in {names['line']}:
            continue
        {names['key']}, {names['value']} = {names['line']}.split("=", 1)
        {names['key']} = {names['key']}.strip()
        {names['value']} = {names['value']}.strip()
{strip_quotes}        {names['result']}[{names['key']}] = {names['value']}
    return {names['result']}"""
    bug_note = "keep their quotes (BUG)" if keep_quotes else "have their quotes stripped"
    return (
        '"""Parse ``key=value`` lines into a dict (values may be quoted)."""\n'
        "from __future__ import annotations\n"
        f"{helper_src}\n"
        "\n"
        "\n"
        "def solve(text: str) -> dict[str, str]:\n"
        f'    """Parse ``key=value`` lines; quoted values {bug_note}."""\n'
        f"{body}\n"
    )


def _sampler_parser(rng: random.Random) -> tuple[str, ...]:
    n = rng.randint(1, 4)
    lines = []
    for _ in range(n):
        k = rng.choice(["a", "bb", "key", "x_y", "z"])
        quoted = rng.random() < 0.4
        if quoted:
            v = rng.choice(["v1", "hello", "12", "a b"])
            lines.append(f'{k}="{v}"')
        else:
            v = rng.choice(["1", "two", "x", "99"])
            lines.append(f"{k}={v}")
    return ("\n".join(lines),)


def _build_parser(rng: random.Random) -> SourceInstance:
    names, helper = _parser_sources(rng)
    buggy = _render_parser(names, helper, keep_quotes=True)
    fixed = _render_parser(names, helper, keep_quotes=False)
    task = (
        "Fix the parser: values wrapped in double quotes must have the "
        "quotes stripped. Lines without ``=`` are ignored. Hidden tests cover "
        "quoted values and multi-line input."
    )
    return SourceInstance(
        template="parser",
        task_kind="repair",
        task=task,
        buggy=buggy,
        fixed=fixed,
        sampler=_sampler_parser,
    )


# ---------------------------------------------------------------------- cache

def _render_cache(
    capacity: int,
    class_name: str,
    data_name: str,
    order_name: str,
    put_name: str,
    get_name: str,
    keep_bug: bool,
) -> str:
    if keep_bug:
        put_update = (
            f"            self.{data_name}[key] = value\n"
            "            return\n"
        )
        get_body = (
            "        # BUG: a read does not refresh recency.\n"
            f"        return self.{data_name}.get(key)\n"
        )
    else:
        put_update = (
            f"            self.{data_name}[key] = value\n"
            f"            self.{order_name}.remove(key)\n"
            f"            self.{order_name}.append(key)\n"
            "            return\n"
        )
        get_body = (
            f"        if key not in self.{data_name}:\n"
            "            return None\n"
            f"        self.{order_name}.remove(key)\n"
            f"        self.{order_name}.append(key)\n"
            f"        return self.{data_name}[key]\n"
        )
    return (
        '"""A fixed-capacity key-value cache (LRU eviction)."""\n'
        "from __future__ import annotations\n"
        "\n"
        "\n"
        f"class {class_name}:\n"
        f"    def __init__(self, capacity: int) -> None:\n"
        "        self.capacity = capacity\n"
        f"        self.{data_name}: dict[str, int] = {{}}\n"
        f"        self.{order_name}: list[str] = []\n"
        "\n"
        f"    def {put_name}(self, key: str, value: int) -> None:\n"
        f"        if key in self.{data_name}:\n"
        f"{put_update}"
        f"        if len(self.{data_name}) >= self.capacity:\n"
        f"            evict = self.{order_name}.pop(0)\n"
        f"            del self.{data_name}[evict]\n"
        f"        self.{data_name}[key] = value\n"
        f"        self.{order_name}.append(key)\n"
        "\n"
        f"    def {get_name}(self, key: str) -> int | None:\n"
        f"{get_body}\n"
        "\n"
        "\n"
        "def solve(ops: list[tuple[str, Any]]) -> list[int | None]:\n"
        '    """Run an op script; return the list of ``get`` results."""\n'
        f"    cache = {class_name}(capacity={capacity})\n"
        "    out: list[int | None] = []\n"
        "    for op, *args in ops:\n"
        f'        if op == "put":\n'
        f"            cache.{put_name}(args[0], args[1])\n"
        f'        elif op == "get":\n'
        f"            out.append(cache.{get_name}(args[0]))\n"
        "    return out\n"
    )


def _sampler_cache(rng: random.Random, capacity: int) -> tuple[list[tuple[str, Any]], ...]:
    """Sample a cache op script for a *capacity*-sized cache.

    Keys are ``capacity + 1`` distinct keys, so the discriminating shape can
    force an eviction. Two script shapes are produced so the classifier can
    separate public from hidden cases:

    - **all-puts-first**: every key is written before any read, so the LRU
      recency bug never changes the observed output (buggy == fixed) — a
      NoOp patch passes these (public hint).
    - **interleaved**: a read happens between writes, so the buggy cache
      evicts a still-recent key that the fixed cache keeps (buggy != fixed) —
      a NoOp patch fails these (hidden negative control).
    """
    keys = [f"k{i}" for i in range(capacity + 1)]
    rng.shuffle(keys)
    ops: list[tuple[Any, ...]] = []
    if rng.random() < 0.5:
        # All writes first, then reads: recency bug is not observable.
        for k in keys:
            ops.append(("put", k, rng.randint(1, 99)))
        for k in keys:
            ops.append(("get", k))
    else:
        # Fill the cache, read the oldest key, then force one eviction:
        # the buggy cache evicts the read key, the fixed one evicts a
        # different key -> observed outputs differ.
        for k in keys[:capacity]:
            ops.append(("put", k, rng.randint(1, 99)))
        ops.append(("get", keys[0]))
        ops.append(("put", keys[capacity], rng.randint(1, 99)))
        ops.append(("get", keys[0]))
        ops.append(("get", keys[1]))
    return (ops,)


def _build_cache(rng: random.Random) -> SourceInstance:
    capacity = 2 if rng.random() < 0.5 else 3
    class_name = _pick(rng, "_Cache", "_Store")
    data_name = _pick(rng, "_data", "_entries")
    order_name = _pick(rng, "_order", "_recency")
    put_name = _pick(rng, "put", "write")
    get_name = _pick(rng, "get", "read")
    buggy = _render_cache(
        capacity, class_name, data_name, order_name, put_name, get_name, keep_bug=True
    )
    fixed = _render_cache(
        capacity, class_name, data_name, order_name, put_name, get_name, keep_bug=False
    )
    task = (
        "Fix the cache: a ``get`` must refresh recency (LRU). With "
        f"capacity {capacity}, after inserting {capacity} keys and reading the "
        "oldest, inserting one more must evict the least-recently-used key. "
        "Hidden tests exercise eviction order."
    )
    return SourceInstance(
        template="cache",
        task_kind="repair",
        task=task,
        buggy=buggy,
        fixed=fixed,
        sampler=lambda rng: _sampler_cache(rng, capacity),
    )


# ---------------------------------------------------------------------- state machine

def _render_state(tokens: tuple[str, str, str], state_name: str, keep_bug: bool) -> str:
    start, tick, finish = tokens
    if keep_bug:
        run_tick = f'            {state_name} = "IDLE"\n'
    else:
        run_tick = f'            {state_name} = "RUN"\n'
    return (
        '"""A minimal state machine (tick resets the machine)."""\n'
        if keep_bug
        else '"""A minimal state machine."""\n'
    ) + (
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def solve(events: list[str]) -> str:\n"
        f'    """Advance a machine; RUN must stay RUN on {tick!r}."""\n'
        f"    {state_name} = \"IDLE\"\n"
        "    for ev in events:\n"
        f'        if {state_name} == "IDLE" and ev == {start!r}:\n'
        f'            {state_name} = "RUN"\n'
        f'        elif {state_name} == "RUN" and ev == {tick!r}:\n'
        f"{run_tick}"
        f'        elif {state_name} == "RUN" and ev == {finish!r}:\n'
        f'            {state_name} = "DONE"\n'
        f'        elif {state_name} == "DONE":\n'
        f'            {state_name} = "DONE"\n'
        f"    return {state_name}\n"
    )


def _sampler_state(rng: random.Random, tokens: tuple[str, str, str]) -> tuple[list[str], ...]:
    start, tick, finish = tokens
    events = [start]
    if rng.random() < 0.5:
        events.append(finish)
    else:
        for _ in range(rng.randint(1, 3)):
            events.append(tick)
        events.append(finish)
    return (events,)


def _build_state_machine(rng: random.Random) -> SourceInstance:
    tokens = rng.choice((("start", "tick", "finish"), ("go", "advance", "end")))
    state_name = _pick(rng, "state", "status")
    buggy = _render_state(tokens, state_name, keep_bug=True)
    fixed = _render_state(tokens, state_name, keep_bug=False)
    start, tick, finish = tokens
    task = (
        f"Fix the state machine: a RUN state must stay RUN on a {tick!r} "
        f"event. Hidden tests exercise {tick} loops between {start!r} and "
        f"{finish!r}."
    )
    return SourceInstance(
        template="state_machine",
        task_kind="repair",
        task=task,
        buggy=buggy,
        fixed=fixed,
        sampler=lambda rng: _sampler_state(rng, tokens),
    )


# ---------------------------------------------------------------------- serialization

def _render_ser(
    sep: str,
    parts_name: str,
    fmt: Callable[[str, str], str],
    keep_bug: bool,
) -> str:
    expr = fmt("k", "v")
    if keep_bug:
        build = (
            f"    {parts_name} = []\n"
            f"    for k, v in items.items():\n"
            f"        {parts_name}.append({expr})\n"
        )
    else:
        build = f"    {parts_name} = [{expr} for k, v in sorted(items.items())]\n"
    return (
        '"""Encode / decode a compact ``k=v,...`` line format."""\n'
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def solve(items: dict[str, int]) -> str:\n"
        '    """Encode an int dict as ``k=v,k=v`` with keys sorted."""\n'
        f"{build}"
        f"    return {sep!r}.join({parts_name})\n"
    )


def _sampler_ser(rng: random.Random) -> tuple[dict[str, int], ...]:
    keys = rng.sample(["a", "b", "c", "d", "e"], rng.randint(1, 4))
    rng.shuffle(keys)
    return ({k: rng.randint(-5, 5) for k in keys},)


def _build_serialization(rng: random.Random) -> SourceInstance:
    sep = "," if rng.random() < 0.5 else ";"
    parts_name = _pick(rng, "parts", "chunks")

    def fmt_fstring(k: str, v: str) -> str:
        return f"f'{{{k}}}={{{v}}}'"

    def fmt_format(k: str, v: str) -> str:
        return f"'{{}}={{}}'.format({k}, {v})"

    fmt = fmt_fstring if rng.random() < 0.5 else fmt_format
    buggy = _render_ser(sep, parts_name, fmt, keep_bug=True)
    fixed = _render_ser(sep, parts_name, fmt, keep_bug=False)
    task = (
        f"Implement ``solve`` to encode a dict as ``k=v{sep}k=v`` with keys "
        "sorted lexicographically. Hidden tests check sorted output."
    )
    return SourceInstance(
        template="serialization",
        task_kind="implementation",
        task=task,
        buggy=buggy,
        fixed=fixed,
        sampler=_sampler_ser,
    )


# ---------------------------------------------------------------------- scheduler

def _render_sched(names: dict[str, str], key_fn: bool, keep_bug: bool) -> str:
    if keep_bug:
        body = f"    return [{names['task_id']} for {names['task_id']}, _ in {names['tasks']}]\n"
    elif key_fn:
        body = (
            f"    return [{names['task_id']} for {names['task_id']}, _ in "
            f"sorted({names['tasks']}, key={names['priority']})]\n"
        )
    else:
        body = (
            f"    return [{names['task_id']} for {names['task_id']}, {names['prio']} in "
            f"sorted({names['tasks']}, key=lambda x: x[1])]\n"
        )
    key_src = (
        f"\n\ndef {names['priority']}(pair: tuple[str, int]) -> int:\n"
        f"    return pair[1]\n"
        if key_fn
        else ""
    )
    return (
        '"""A priority task scheduler."""\n'
        "from __future__ import annotations\n"
        f"{key_src}"
        "\n"
        "\n"
        f"def solve({names['tasks']}: list[tuple[str, int]]) -> list[str]:\n"
        '    """Return task ids in priority order (lower int = higher priority)."""\n'
        f"{body}"
    )


def _sampler_sched(rng: random.Random) -> tuple[list[tuple[str, int]], ...]:
    names = [f"t{i}" for i in range(rng.randint(1, 5))]
    tasks = [(n, rng.randint(0, 4)) for n in names]
    return (tasks,)


def _build_scheduler(rng: random.Random) -> SourceInstance:
    names = {
        "task_id": _pick(rng, "t", "task"),
        "tasks": _pick(rng, "tasks", "jobs"),
        "prio": _pick(rng, "p", "prio"),
        "priority": _pick(rng, "_priority", "_weight"),
    }
    key_fn = rng.random() < 0.5
    buggy = _render_sched(names, key_fn, keep_bug=True)
    fixed = _render_sched(names, key_fn, keep_bug=False)
    task = (
        "Implement ``solve`` to return task ids ordered by priority "
        "(lower integer wins). Hidden tests check ordering."
    )
    return SourceInstance(
        template="scheduler",
        task_kind="implementation",
        task=task,
        buggy=buggy,
        fixed=fixed,
        sampler=_sampler_sched,
    )


# ---------------------------------------------------------------------- storage

def _render_storage(tokens: tuple[str, ...], names: dict[str, str], keep_bug: bool) -> str:
    begin, set_, commit, rollback, get_ = tokens
    data, tx = names["data"], names["tx"]
    if keep_bug:
        commit_body = (
            f"                {tx} = None  # BUG: writes are not persisted\n"
        )
    else:
        commit_body = (
            f"                {data} = dict({tx})\n"
            f"                {tx} = None\n"
        )
    return (
        '"""A tiny KV store with a single-level transaction."""\n'
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def solve(ops: list[tuple[str, Any]]) -> list[str | None]:\n"
        '    """Run a KV op script; return ``get`` results."""\n'
        f"    {data}: dict[str, str] = {{}}\n"
        f"    {tx}: dict[str, str] | None = None\n"
        "    out: list[str | None] = []\n"
        "    for op, *args in ops:\n"
        f"        if op == {begin!r}:\n"
        f"            {tx} = dict({data})\n"
        f"        elif op == {set_!r}:\n"
        f"            if {tx} is not None:\n"
        f"                {tx}[args[0]] = args[1]\n"
        "            else:\n"
        f"                {data}[args[0]] = args[1]\n"
        f"        elif op == {commit!r}:\n"
        f"            if {tx} is not None:\n"
        f"{commit_body}"
        f"        elif op == {rollback!r}:\n"
        f"            {tx} = None\n"
        f"        elif op == {get_!r}:\n"
        f"            src = {tx} if {tx} is not None else {data}\n"
        "            out.append(src.get(args[0]))\n"
        "    return out\n"
    )


def _sampler_storage(
    rng: random.Random, tokens: tuple[str, ...]
) -> tuple[list[tuple[str, Any]], ...]:
    begin, set_, commit, rollback, get_ = tokens
    keys = ["k", "a", "b", "c"]
    ops: list[tuple[Any, ...]] = []
    ops.append((begin,))
    for _ in range(rng.randint(1, 3)):
        ops.append((set_, rng.choice(keys), rng.choice(["v", "x", "y"])))
    if rng.random() < 0.5:
        ops.append((commit,))
    else:
        ops.append((rollback,))
    ops.append((get_, rng.choice(keys)))
    return (ops,)


def _build_storage(rng: random.Random) -> SourceInstance:
    tokens = rng.choice(
        (
            ("begin", "set", "commit", "rollback", "get"),
            ("open", "write", "commit", "abort", "read"),
        )
    )
    names = {
        "data": _pick(rng, "data", "store"),
        "tx": _pick(rng, "tx", "pending"),
    }
    buggy = _render_storage(tokens, names, keep_bug=True)
    fixed = _render_storage(tokens, names, keep_bug=False)
    begin, set_, commit, rollback, get_ = tokens
    task = (
        f"Fix the KV store: {commit!r} must persist open-transaction writes "
        f"into the store; {rollback!r} must discard them. Hidden tests check "
        f"commit persistence."
    )
    return SourceInstance(
        template="storage",
        task_kind="repair",
        task=task,
        buggy=buggy,
        fixed=fixed,
        sampler=lambda rng: _sampler_storage(rng, tokens),
    )


TEMPLATES: dict[str, Template] = {
    t.name: t
    for t in (
        Template(name="parser", task_kind="repair", builder=_build_parser),
        Template(name="cache", task_kind="repair", builder=_build_cache),
        Template(name="state_machine", task_kind="repair", builder=_build_state_machine),
        Template(name="serialization", task_kind="implementation", builder=_build_serialization),
        Template(name="scheduler", task_kind="implementation", builder=_build_scheduler),
        Template(name="storage", task_kind="repair", builder=_build_storage),
    )
}

TEMPLATE_NAMES = tuple(sorted(TEMPLATES))


def template_for(seed: str) -> Template:
    """Deterministically pick a template from a seed."""
    rng = random.Random(f"repo-v0.1:template-select:{seed}")
    return TEMPLATES[rng.choice(TEMPLATE_NAMES)]


def build_source_instance(template: Template, instance_rng: random.Random) -> SourceInstance:
    """Assemble one concrete source instance from an instance RNG.

    The generator supplies a verifier-secret-bound ``instance_rng``; without
    the secret, a released challenge's fixed source / reference patch cannot
    be reproduced (docs/SPEC.md "Verifier material"). This is the ONLY path
    that produces the reference implementation.
    """
    return template.builder(instance_rng)


def run_source(src: str, args: tuple[Any, ...]) -> Any:
    """Execute a source string in an isolated namespace and call ``solve``."""
    return _run_source(src, args)


__all__ = [
    "SourceInstance",
    "TEMPLATES",
    "TEMPLATE_NAMES",
    "Template",
    "build_source_instance",
    "classify_hidden",
    "classify_public",
    "run_source",
    "template_for",
]
