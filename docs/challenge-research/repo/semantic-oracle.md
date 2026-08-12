# REPO-v0.1 Semantic Oracle Verifier

> Status: **Implemented (generator `0.3.0`, v1.0.2)** — the authoritative
> expected value for every template is now an independent `input -> expected`
> function (the **semantic oracle**), not a recoverable reference source. This
> document records the design and the audit basis for closing the
> exact-reference-source lookup flagged in `docs/reports/repo-v0.1-validation.md`
> (Route A).

## 1. Problem: exact-reference-source lookup

REPO-v0.1's public `Template.builder` (open source, installed in the published
wheel) enumerates a finite variant space. An attacker holding the **public
`solution.py`** + **template name** + **installed public VICA package** can sweep
that space, match `instance.buggy == solution.py`, and recover the exact
`instance.fixed` (reference) source. The attack was empirically confirmed on the
`parser` template with only a handful of probe seeds.

The recovered `fixed` source let an attacker read off the "correct" answer
without solving the task, so the benchmark could not distinguish a system that
recovered the reference material from one that genuinely repaired the code.

Per research-integrity policy this is **not** closed by HMAC / extra random
variables / private naming / obfuscation — those do not remove the lookup, they
only make it marginally harder. The fix must **eliminate the lookup** by making
the authoritative expected value independent of any recoverable source string.

## 2. Design: the semantic oracle

For each template, the authoritative expected value for a given input now comes
from a **per-template semantic oracle**: a pure, deterministic

```text
oracle: input -> expected
```

function of the template's semantics and the instance's *public* parameters
(cache capacity, state tokens, separator). It never reads a per-instance source
string, so the expected value is pinned to the **public spec**, not to any
recoverable `fixed` source.

The oracle is public by design: it *is* the task specification. Because the
oracle makes the correct behavior explicit, an attacker who recovers
`instance.fixed` by enumerating the open-source builder gains **no advantage**:
fixing the workspace to match the public oracle spec is the honest task, and the
reference patch becomes just one of many equivalent correct implementations.
The reference-source lookup is thus neutralized as a benchmark shortcut, not
obfuscated.

### 2.1 Why this removes the lookup

| old (0.2.0) | new (0.3.0) |
|--------------|-------------|
| expected derived by executing a recoverable `fixed` source | expected derived from an independent pure oracle |
| recovering `fixed` → attacker learns the "answer" | recovering `fixed` → no advantage, oracle is public |
| correctness depends on secrecy of `fixed` | correctness depends only on the public spec |

The reference patch (git diff `buggy -> fixed`) is **retained** as a
calibration / positive control, generated only in the authoritative path
(`generate_with_solution`). It is never shipped to solvers.

## 3. Per-template oracle contracts

Each template binds a concrete oracle in its builder, capturing only the
instance's *public* parameters (never a source string). Reference:
`src/vica/repo/templates.py`.

| template | oracle | input | expected |
|----------|--------|-------|----------|
| `parser` | `_oracle_parser` | text | `dict[str, str]` of `key=value` lines; quoted values have quotes stripped; lines without `=` ignored |
| `cache` | `_oracle_cache(ops, capacity)` | op list | `list[int | None]` of `get` results under an LRU policy (get refreshes recency; evict LRU on overflow) |
| `state_machine` | `_oracle_state(events, tokens)` | event list | `"IDLE" / "RUN" / "DONE"` per start/tick/finish semantics |
| `serialization` | `_oracle_ser(items, sep)` | int dict | `"k=v{sep}k=v"` with keys sorted |
| `scheduler` | `_oracle_sched` | task list | task ids in priority order (lower int = higher priority) |
| `storage` | `_oracle_storage(ops, tokens)` | op list | `list[str | None]` of `get` results under a single-level transaction KV store (commit persists tx writes, rollback discards) |

Each oracle is a pure function of the input plus the listed public parameters.
`test_oracle_is_pure_function_of_input` asserts determinism across independent
instances of the same template; `test_oracle_matches_fixed_semantics` asserts
each oracle agrees with the authoritative `fixed` source on 25 sampled inputs per
template, so the reference patch stays consistent with the public spec.

## 4. Implementation

- **`SourceInstance.oracle: Callable`** — new field on the dataclass
  (`src/vica/repo/templates.py`). Bound in each `_build_*` builder.
- **Classification against the oracle** — `classify_public` / `classify_hidden`
  now compare `buggy` output against `instance.oracle(*args)` instead of
  executing `instance.fixed`. Public cases are inputs where `buggy == oracle`
  (NoOp passes); hidden cases are inputs where `buggy != oracle` (NoOp fails).
- **Generator `0.3.0`** — `GENERATOR_VERSION = "0.3.0"`
  (`src/vica/repo/generator.py`). Hidden-test expected values are computed by
  the oracle; the reference patch remains a positive control.
- **Family gate** — `src/vica/repo/family.py` refuses any challenge whose
  `generator_version` is not `0.3.0` with `WITHDRAWN_GENERATOR`. Both withdrawn
  historical semantics (0.1.0 shared-interpreter, 0.2.0 recoverable
  fixed-source) are in `WITHDRAWN_GENERATOR_VERSIONS`
  (`src/vica/eval/bundle.py`).
- **Task Pack version** — the REPO-family pack version bumps `2 -> 3`
  (`src/vica/eval/taskpack.py`) because the authoritative expected-value
  derivation changed; packs/results built under 0.2.0 semantics are not silently
  re-identified under 0.3.0.

## 5. Invariants and regression coverage (`tests/test_repo_integrity.py`)

- `test_classification_expected_comes_from_oracle` — public/hidden expected
  values equal `instance.oracle(*args)` for every template.
- `test_oracle_matches_fixed_semantics` — oracle agrees with the authoritative
  reference source on sampled inputs.
- `test_oracle_is_pure_function_of_input` — oracle is a deterministic pure
  function of the input (+ public parameters), independent of the per-instance
  source string.
- `test_former_generator_020_denied_at_family` — a challenge claiming the
  superseded 0.2.0 generator is refused with `WITHDRAWN_GENERATOR`.
- `test_generator_version_bumped` — asserts `0.3.0`.
- `test_task_pack_version_is_family_scoped` — REPO family is `3`, other
  families stay `1`.

## 6. What is established vs not claimed

Established to current tests:

- The authoritative expected value is independent of a recoverable reference
  source (oracle is public and pure).
- Recovering `instance.fixed` yields no expected-value advantage.
- Historical 0.1.0 / 0.2.0 semantics are withdrawn and refused.

The reference-source lookup is thus **closed** for the enumerated templates by
the oracle design. This is a verifier-correctness claim, auditable by reading
the oracle functions; it is **not** a hardened-hostile-code-isolation claim (the
sandbox remains experimental local process isolation, per `threat-model.md`).