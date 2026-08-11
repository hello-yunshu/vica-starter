# VICA Reproducibility

> Status: **v0.4.0** — Execution Profile + environment provenance, Task Pack
> identity, and multi-run Study orchestration are implemented and tested. The
> local runner is the stable backend; Docker isolation, if present, is
> experimental.

This document describes what VICA makes reproducible, how, and — equally
importantly — what it does **not** claim to reproduce. It complements
`docs/BENCHMARK_METHODOLOGY.md` (metrics) and `docs/SPEC.md` (protocol).

## 1. Execution Profile

Every Result Bundle records an **Execution Profile** that captures the
environment a run was produced under, without exposing secrets:

| field | meaning |
|-------|---------|
| `runner_backend` | `local` (stable) or `docker` (experimental, if present) |
| `os` / `architecture` | host OS and machine architecture |
| `python_version` / `python_implementation` | interpreter identity |
| `dependency_environment_hash` | SHA-256 of installed provenance-relevant package versions |
| `vica_version` / `git_commit` | VICA release and exact source revision |
| `timeout_s` / `cpu_budget` / `memory_budget` | runtime policies |
| `network_policy` | `default` / `none` |
| `passed_env_names` | **names only** of forwarded env vars — never values |
| `agent_command` | identity of the agent command (for Agent runs) |

See `src/vica/eval/environment.py`. The profile is produced by a VICA-owned run
(Agent / Command Solver) and carried in the submission's `system_metadata`;
file-exchange submissions get a local default profile so provenance is always
present.

### Secret values are never recorded (§64)

Provenance may record that `OPENAI_API_KEY` was **supplied**, but never its
value. The same holds for `ANTHROPIC_API_KEY`, tokens, and credentials. The
verifier-reserved secrets (`VICA_VERIFIER_SECRET`, `VICA_PRIVATE_*`) are never
forwarded to an agent and never written to any bundle.

## 2. Task Pack identity

A **Task Pack** is the stable, versioned identity of a benchmark instance set
(the concrete challenge ids, and for REPO their workspace hashes). It is what
makes a result comparable across systems and runs:

- `task_pack_id` — stable logical family name (e.g. `repo-v0.1-core`).
- `task_pack_version` — bumped whenever task *semantics* change; a released
  task pack is never silently mutated.
- `task_pack_hash` — SHA-256 of the canonical serialization of the task-set
  definition. Two runs over the same task set always produce the same hash.

A Result Bundle records `task_pack_id` / `task_pack_version` / `task_pack_hash`,
and strict reverify binds the hash so a tampered result set is detected even
when valid/score happen to coincide.

See `src/vica/eval/taskpack.py`.

## 3. Study: replicates and multi-run benchmarks

A **Study** runs every system × every task × every replicate and aggregates
results (success rate with Wilson CI, latency, failure taxonomy, per-difficulty
correctness). Replicates are part of the **run** identity — never the Challenge
or Task Pack identity — so a stochastic agent's pass probability, median
latency, and failure distribution are reported, never just its best attempt.

```bash
vica study run \
  --evaluation <eval-root> \
  --out <study-dir> \
  --systems '[{"system_id":"noop","kind":"noop"},{"system_id":"reference","kind":"reference"}]' \
  --replicates 3 \
  --verifier-secret "$VICA_VERIFIER_SECRET"
```

See `src/vica/eval/study.py` and `src/vica/eval/stats.py`.

## 4. Stable backend: `local`

The `local` backend materializes each REPO workspace into a fresh scratch
directory, runs the agent with that workspace as `cwd`, captures the patch, and
discards the scratch. It is the stable, reproducible default.

## 5. Optional Docker backend (experimental)

If Docker is present on the host, a minimal Docker backend may be used. It is
**not** a v1.0 dependency. When used:

- the agent container mounts only the public scratch workspace;
- it never mounts VICA private evaluation material, `$HOME`, or the host repo;
- the evaluator stays on the host/private side and only takes the resulting
  workspace modifications / patch;
- network is `none` by default, with an explicit opt-in `default` for agents
  that require their own API key (forwarded explicitly, never secrets).

`VICA_VERIFIER_SECRET` is never passed to the agent container (local or Docker);
this is a regression-tested invariant.

## 6. What is reproducible

- Challenge generation from declared identity inputs (version + seed +
  difficulty) and the verifier-material commitment for secret-bound families.
- Deterministic verification (same inputs → same result).
- The set of tasks in a result, via the Task Pack hash.
- The environment a run was produced under, via the Execution Profile.
- Strict reverify: given the same Evaluation Bundle + verifier material + a
  Result Bundle, a third party recomputes identical valid/score/error semantics
  without calling the solver.

## 7. What is NOT reproduced

- **Secret values** are never stored or reproduced.
- **Agent runtime behavior** is inherently stochastic; replicates characterize
  but do not eliminate it.
- **Hardened host isolation** is **not** claimed; the OS sandbox is experimental
  local process isolation (see `docs/challenge-research/repo/threat-model.md`).
- **Commercial-agent rankings** are only reported if actually measured; a run
  with no real agent reports `Not Measured`, never a fabricated number.