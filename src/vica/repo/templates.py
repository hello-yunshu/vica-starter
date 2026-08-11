"""REPO-v0.1 task templates.

Each template is a small, self-contained Python *function* workspace. The
candidate patch must fix or implement a module-level ``solve`` function. To
keep the v0.3 runner uniform and deterministic every template exposes exactly
one entry point:

    solution.solve(*args) -> Any

A template provides the *buggy* (workspace) and *fixed* (reference-only)
sources, a task description, and an input sampler used to generate public and
hidden cases. The generator classifies inputs automatically:

- **public** cases are inputs on which ``buggy == fixed`` (a NoOp patch passes
  public tests — the honest hint);
- **hidden** cases are inputs on which ``buggy != fixed`` (a NoOp patch fails
  them — the discriminating negative control).

This guarantees, for every released task: NoOp fails hidden, Reference passes
all, and a public-only naive repair passes public but fails hidden.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Template:
    name: str
    task_kind: str  # "repair" | "implementation"
    task: str
    buggy: str
    fixed: str
    sampler: Callable[[random.Random], tuple[Any, ...]]
    # Optional: number of public / hidden cases to generate.
    public_count: int = 6
    hidden_count: int = 12


_ARGV = "__vica_args__"


def _run_source(src: str, args: tuple[Any, ...]) -> Any:
    """Execute a template source in an isolated namespace and call ``solve``."""
    ns: dict[str, Any] = {}
    exec(compile(src, "<template>", "exec"), ns)  # trusted template code
    return ns["solve"](*args)


def _classify(
    template: Template,
    sampler: Callable[[random.Random], tuple[Any, ...]],
    rng: random.Random,
    public_count: int,
    hidden_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split sampled inputs into public (buggy==fixed) and hidden (buggy!=fixed)."""
    public = classify_public(template, rng, count=public_count)
    hidden = classify_hidden(template, rng, count=hidden_count)
    return public, hidden


def _classify_set(
    template: Template,
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
        args = template.sampler(rng)
        try:
            expected = _run_source(template.fixed, args)
        except Exception:
            continue
        try:
            buggy_out = _run_source(template.buggy, args)
        except Exception:
            buggy_out = _MISSING
        if (buggy_out == expected) is want_public:
            collected.append({"args": list(args), "expected": expected})
    if len(collected) < count:
        raise RuntimeError(
            f"template {template.name}: could not classify enough "
            f"{'public' if want_public else 'hidden'} cases "
            f"({len(collected)}/{count})"
        )
    return collected


def classify_public(
    template: Template,
    rng: random.Random,
    *,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """Collect inputs on which the buggy and fixed sources agree (public tests)."""
    return _classify_set(template, rng, count or template.public_count, want_public=True)


def classify_hidden(
    template: Template,
    rng: random.Random,
    *,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """Collect inputs on which the buggy and fixed sources disagree (hidden tests)."""
    return _classify_set(template, rng, count or template.hidden_count, want_public=False)


class _Missing:
    def __eq__(self, other: Any) -> bool:
        return False

    def __repr__(self) -> str:  # pragma: no cover
        return "<missing>"


_MISSING = _Missing()


# ---------------------------------------------------------------------- parser

_PARSER_BUGGY = '''"""Parse key=value lines into a dict (values may be quoted)."""
from __future__ import annotations


def solve(text: str) -> dict[str, str]:
    """Parse ``key=value`` lines; quoted values keep their quotes (BUG)."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result
'''

_PARSER_FIXED = '''"""Parse key=value lines into a dict (values may be quoted)."""
from __future__ import annotations


def solve(text: str) -> dict[str, str]:
    """Parse ``key=value`` lines; quoted values have their quotes stripped."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[key] = value
    return result
'''


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


def _parser() -> Template:
    return Template(
        name="parser",
        task_kind="repair",
        task="Fix the parser: values wrapped in double quotes must have the "
        "quotes stripped. Lines without ``=`` are ignored. Hidden tests cover "
        "quoted values and multi-line input.",
        buggy=_PARSER_BUGGY,
        fixed=_PARSER_FIXED,
        sampler=_sampler_parser,
    )


# ---------------------------------------------------------------------- cache

_CACHE_BUGGY = '''"""A fixed-capacity key-value cache (LRU eviction)."""
from __future__ import annotations


class _Cache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._data: dict[str, int] = {}
        self._order: list[str] = []

    def put(self, key: str, value: int) -> None:
        if key in self._data:
            self._data[key] = value
            return
        if len(self._data) >= self.capacity:
            evict = self._order.pop(0)
            del self._data[evict]
        self._data[key] = value
        self._order.append(key)

    def get(self, key: str) -> int | None:
        # BUG: a read does not refresh recency.
        return self._data.get(key)


def solve(ops: list[tuple[str, Any]]) -> list[int | None]:
    """Run an op script; return the list of ``get`` results."""
    cache = _Cache(capacity=2)
    out: list[int | None] = []
    for op, *args in ops:
        if op == "put":
            cache.put(args[0], args[1])
        elif op == "get":
            out.append(cache.get(args[0]))
    return out
'''

_CACHE_FIXED = '''"""A fixed-capacity key-value cache (LRU eviction)."""
from __future__ import annotations


class _Cache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._data: dict[str, int] = {}
        self._order: list[str] = []

    def put(self, key: str, value: int) -> None:
        if key in self._data:
            self._data[key] = value
            self._order.remove(key)
            self._order.append(key)
            return
        if len(self._data) >= self.capacity:
            evict = self._order.pop(0)
            del self._data[evict]
        self._data[key] = value
        self._order.append(key)

    def get(self, key: str) -> int | None:
        if key not in self._data:
            return None
        self._order.remove(key)
        self._order.append(key)
        return self._data[key]


def solve(ops: list[tuple[str, Any]]) -> list[int | None]:
    cache = _Cache(capacity=2)
    out: list[int | None] = []
    for op, *args in ops:
        if op == "put":
            cache.put(args[0], args[1])
        elif op == "get":
            out.append(cache.get(args[0]))
    return out
'''


def _sampler_cache(rng: random.Random) -> tuple[list[tuple[str, Any]], ...]:
    """Sample a cache op script.

    Capacity is fixed at 2 (see the template source). Two script shapes are
    produced so the classifier can separate public from hidden cases:

    - **all-puts-first**: every key is written before any read, so the LRU
      recency bug never changes the observed output (buggy == fixed) — a
      NoOp patch passes these (public hint).
    - **interleaved**: a read happens between writes, so the buggy cache
      evicts a still-recent key that the fixed cache keeps (buggy != fixed) —
      a NoOp patch fails these (hidden negative control).
    """
    keys = ["a", "b", "c"]
    rng.shuffle(keys)
    ops: list[tuple[Any, ...]] = []
    if rng.random() < 0.5:
        # All writes first, then reads: recency bug is not observable.
        for k in keys:
            ops.append(("put", k, rng.randint(1, 99)))
        ops.append(("get", keys[0]))
        ops.append(("get", keys[1]))
        ops.append(("get", keys[2]))
    else:
        # Interleave a read before the evicting write: recency bug is exposed.
        ops.append(("put", keys[0], rng.randint(1, 99)))
        ops.append(("put", keys[1], rng.randint(1, 99)))
        ops.append(("get", keys[0]))
        ops.append(("put", keys[2], rng.randint(1, 99)))
        ops.append(("get", keys[0]))
        ops.append(("get", keys[1]))
        ops.append(("get", keys[2]))
    return (ops,)


def _cache() -> Template:
    return Template(
        name="cache",
        task_kind="repair",
        task="Fix the cache: a ``get`` must refresh recency (LRU). With "
        "capacity 2, after inserting a,b and reading b, inserting c must "
        "evict a (not b). Hidden tests exercise eviction order.",
        buggy=_CACHE_BUGGY,
        fixed=_CACHE_FIXED,
        sampler=_sampler_cache,
    )


# ---------------------------------------------------------------------- state machine

_STATE_BUGGY = '''"""A minimal state machine (tick resets the machine)."""
from __future__ import annotations


def solve(events: list[str]) -> str:
    """Advance a machine; RUN must stay RUN on tick (BUG: resets to IDLE)."""
    state = "IDLE"
    for ev in events:
        if state == "IDLE" and ev == "start":
            state = "RUN"
        elif state == "RUN" and ev == "tick":
            state = "IDLE"
        elif state == "RUN" and ev == "finish":
            state = "DONE"
        elif state == "DONE":
            state = "DONE"
    return state
'''

_STATE_FIXED = '''"""A minimal state machine."""
from __future__ import annotations


def solve(events: list[str]) -> str:
    """Advance a machine; RUN stays RUN on tick."""
    state = "IDLE"
    for ev in events:
        if state == "IDLE" and ev == "start":
            state = "RUN"
        elif state == "RUN" and ev in ("tick", "finish"):
            state = "RUN" if ev == "tick" else "DONE"
        elif state == "DONE":
            state = "DONE"
    return state
'''


def _sampler_state(rng: random.Random) -> tuple[list[str], ...]:
    """Sample a state-machine event script.

    Capacity/fixed transition: ``start`` then ``finish`` reaches DONE. A
    ``tick`` between them is the discriminating event:

    - **no tick** (buggy == fixed): start, finish -> DONE (public hint).
    - **tick before finish** (buggy != fixed): the buggy machine resets to
      IDLE on the tick and never reaches DONE (hidden negative control).
    """
    events = ["start"]
    if rng.random() < 0.5:
        events.append("finish")
    else:
        for _ in range(rng.randint(1, 3)):
            events.append("tick")
        events.append("finish")
    return (events,)


def _state_machine() -> Template:
    return Template(
        name="state_machine",
        task_kind="repair",
        task="Fix the state machine: a RUN state must stay RUN on a ``tick`` "
        "event. Hidden tests exercise tick loops.",
        buggy=_STATE_BUGGY,
        fixed=_STATE_FIXED,
        sampler=_sampler_state,
    )


# ---------------------------------------------------------------------- serialization

_SER_BUGGY = '''"""Encode / decode a compact ``k=v,...`` line format."""
from __future__ import annotations


def solve(items: dict[str, int]) -> str:
    """Encode an int dict as ``k=v,k=v`` (BUG: keys not sorted)."""
    parts = []
    for k, v in items.items():
        parts.append(f"{k}={v}")
    return ",".join(parts)
'''

_SER_FIXED = '''"""Encode / decode a compact ``k=v,...`` line format."""
from __future__ import annotations


def solve(items: dict[str, int]) -> str:
    """Encode an int dict as ``k=v,k=v`` with keys sorted."""
    parts = [f"{k}={v}" for k, v in sorted(items.items())]
    return ",".join(parts)
'''


def _sampler_ser(rng: random.Random) -> tuple[dict[str, int], ...]:
    keys = rng.sample(["a", "b", "c", "d", "e"], rng.randint(1, 4))
    rng.shuffle(keys)
    return ({k: rng.randint(-5, 5) for k in keys},)


def _serialization() -> Template:
    return Template(
        name="serialization",
        task_kind="implementation",
        task="Implement ``solve`` to encode a dict as ``k=v,k=v`` with keys "
        "sorted lexicographically. Hidden tests check sorted output.",
        buggy=_SER_BUGGY,
        fixed=_SER_FIXED,
        sampler=_sampler_ser,
    )


# ---------------------------------------------------------------------- scheduler

_SCHED_BUGGY = '''"""A priority task scheduler."""
from __future__ import annotations


def solve(tasks: list[tuple[str, int]]) -> list[str]:
    """Return task ids in priority order (BUG: insertion order kept)."""
    return [t for t, _ in tasks]
'''

_SCHED_FIXED = '''"""A priority task scheduler."""
from __future__ import annotations


def solve(tasks: list[tuple[str, int]]) -> list[str]:
    """Return task ids in priority order (lower int = higher priority)."""
    return [t for t, _ in sorted(tasks, key=lambda x: x[1])]
'''


def _sampler_sched(rng: random.Random) -> tuple[list[tuple[str, int]], ...]:
    names = [f"t{i}" for i in range(rng.randint(1, 5))]
    tasks = [(n, rng.randint(0, 4)) for n in names]
    return (tasks,)


def _scheduler() -> Template:
    return Template(
        name="scheduler",
        task_kind="implementation",
        task="Implement ``solve`` to return task ids ordered by priority "
        "(lower integer wins). Hidden tests check ordering.",
        buggy=_SCHED_BUGGY,
        fixed=_SCHED_FIXED,
        sampler=_sampler_sched,
    )


# ---------------------------------------------------------------------- storage

_STORAGE_BUGGY = '''"""A tiny KV store with a single-level transaction."""
from __future__ import annotations


def solve(ops: list[tuple[str, Any]]) -> list[str | None]:
    """Run a KV op script; return ``get`` results. (BUG: commit drops writes.)"""
    data: dict[str, str] = {}
    tx: dict[str, str] | None = None
    out: list[str | None] = []
    for op, *args in ops:
        if op == "begin":
            tx = dict(data)
        elif op == "set":
            if tx is not None:
                tx[args[0]] = args[1]
            else:
                data[args[0]] = args[1]
        elif op == "commit":
            if tx is not None:
                tx = None  # BUG: writes are not persisted
        elif op == "rollback":
            tx = None
        elif op == "get":
            src = tx if tx is not None else data
            out.append(src.get(args[0]))
    return out
'''

_STORAGE_FIXED = '''"""A tiny KV store with a single-level transaction."""
from __future__ import annotations


def solve(ops: list[tuple[str, Any]]) -> list[str | None]:
    """Run a KV op script; return ``get`` results."""
    data: dict[str, str] = {}
    tx: dict[str, str] | None = None
    out: list[str | None] = []
    for op, *args in ops:
        if op == "begin":
            tx = dict(data)
        elif op == "set":
            if tx is not None:
                tx[args[0]] = args[1]
            else:
                data[args[0]] = args[1]
        elif op == "commit":
            if tx is not None:
                data = dict(tx)
                tx = None
        elif op == "rollback":
            tx = None
        elif op == "get":
            src = tx if tx is not None else data
            out.append(src.get(args[0]))
    return out
'''


def _sampler_storage(rng: random.Random) -> tuple[list[tuple[str, Any]], ...]:
    keys = ["k", "a", "b", "c"]
    ops: list[tuple[Any, ...]] = []
    ops.append(("begin",))
    for _ in range(rng.randint(1, 3)):
        ops.append(("set", rng.choice(keys), rng.choice(["v", "x", "y"])))
    if rng.random() < 0.5:
        ops.append(("commit",))
    else:
        ops.append(("rollback",))
    ops.append(("get", rng.choice(keys)))
    return (ops,)


def _storage() -> Template:
    return Template(
        name="storage",
        task_kind="repair",
        task="Fix the KV store: ``commit`` must persist open-transaction writes "
        "into the store; ``rollback`` must discard them. Hidden tests check "
        "commit persistence.",
        buggy=_STORAGE_BUGGY,
        fixed=_STORAGE_FIXED,
        sampler=_sampler_storage,
    )


TEMPLATES: dict[str, Template] = {
    t.name: t
    for t in (
        _parser(),
        _cache(),
        _state_machine(),
        _serialization(),
        _scheduler(),
        _storage(),
    )
}

TEMPLATE_NAMES = tuple(sorted(TEMPLATES))


def template_for(seed: str) -> Template:
    """Deterministically pick a template from a seed."""
    rng = random.Random(f"repo-v0.1:template-select:{seed}")
    return TEMPLATES[rng.choice(TEMPLATE_NAMES)]


def classify_cases(
    template: Template,
    rng: random.Random,
    *,
    public_count: int | None = None,
    hidden_count: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify sampled inputs into public (buggy==fixed) / hidden (buggy!=fixed)."""
    return _classify(
        template,
        template.sampler,
        rng,
        public_count or template.public_count,
        hidden_count or template.hidden_count,
    )


__all__ = [
    "TEMPLATES",
    "TEMPLATE_NAMES",
    "Template",
    "classify_cases",
    "classify_hidden",
    "classify_public",
    "template_for",
]