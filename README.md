English | [简体中文](README.zh-CN.md)

# VICA

**Verifiable Intelligence Compute Arena** · 可验证智能计算竞技场

A local research arena for measuring how different compute systems — LLMs, coding
agents, traditional algorithms, and hybrid systems — perform on automatically
generated, objectively verifiable tasks.

VICA is not a hosted service. It is a **Local Research Arena**: you generate
challenges, run solvers locally, and evaluate them with a deterministic verifier.

---

## Core Question

VICA studies not "which model chats best", but:

> Under unknown tasks, limited time, and limited budget, which compute system
> produces the most deterministically-verified high-quality solutions at the
> lowest cost?

Design principles:

- **Hard to solve, easy to verify** — compute is the cost; verification is cheap.
- Difficulty is configurable; challenges are generated on demand and unbounded.
- The verifier is deterministic and solver-neutral — **no LLM judge**.
- Models, algorithms, and agents share one solver interface and one verifier.
- Cost, latency, success rate, and solution quality are measured uniformly.

---

## Current Status

VICA is a local research arena. The following components exist today:

| Component | Status | Purpose |
|-----------|--------|---------|
| Protocol Core | Stable | Pydantic models, canonical serialization, interfaces, challenge identity |
| CSP-v0.1 | Stable | Infrastructure validation (constraint satisfaction) |
| Random baseline | Stable | Floor baseline |
| Z3 baseline | Stable | Traditional solver baseline |
| Arena runner | Stable | Challenge generation → solve → verify → record |
| SQLite storage | Stable | Experiments, challenges, systems, runs |
| Export / metrics | Stable | CSV / JSON export, aggregate metrics |
| LLM adapter | Under Review | OpenAI-compatible API path (pricing optional) |
| Evaluation Bundles | Stable | v1/v2 portable Evaluation / Submission / Result bundles |
| Strict Reverify | Stable | Deterministic re-verification of a Result Bundle |
| REPO-v0.1 | Stable | Agent Benchmark — coding-agent workspace + patch verification |
| SYNTH-v0.1 | Experimental | Program-synthesis research (restricted DSL) |
| OPT-v0.1 | Experimental | Continuous solution quality (scheduling) |
| OS sandbox | Experimental | OS resource isolation prototype (see Security) |

"Experimental / Under Review" reflects research maturity, not just code presence.
`src/vica/server/` is intentionally empty — Public API / hosted arena are deferred
(see below).

---

## Security

- SYNTH-v0.1 executes a **restricted DSL interpreter**. It does **not** execute
  arbitrary Python candidate code (no `exec`, no `eval`).
- The OS-level sandbox (`src/vica/sandbox/`) is an **experimental OS resource
  isolation prototype** and MUST NOT currently be treated as a hardened
  hostile-code isolation boundary. Memory limits are Linux-only; network
  namespace / chroot are Linux+root and off by default; the output cap is a
  bounded streaming read that kills the child on overflow (hard enforcement),
  not post-hoc truncation.
- Sandboxed subprocesses inherit a **minimal allowlist environment** — host
  secrets (API keys, tokens) are never passed to a candidate by default.

## Research Integrity

- No LLM judge for correctness — verification is deterministic.
- Solver-neutral verification — the arena does not favor any provider or model.
- Traditional-solver dominance is a valid research outcome.
- Reproducibility metadata (git commit, VICA version, generator version, system
  config, environment manifest, seed) is persisted per experiment.
- Challenge identity is reproducible from its declared inputs: for ordinary
  families `(type, generator_version, seed, difficulty)`; for secret-bound
  families additionally the `verifier_material_commitment` (full SHA-256 over a
  domain-separated string incl. the material version), so same public seed with
  different verifier material yields a different challenge_id.
- The verifier refuses to evaluate hidden material when the supplied secret
  does not commit to the challenge's material: that is an evaluator
  configuration failure (`INTERNAL_ERROR`, reason `verifier_material_mismatch`),
  never a solver `INVALID_SOLUTION`.
- Hidden verifier material (hidden tests, reference solution, verifier secret) is
  isolated from solver inputs. See `docs/SPEC.md` "Verifier Material".

> Development Mode vs Evaluation Mode: a coding agent working directly in the
> repo root can read `src/`. For a truly adversarial hidden benchmark, keep the
> verifier secret / hidden tests / reference solution out of the agent's readable
> workspace and give it only a public challenge bundle.
>
> What Evaluation Mode **guarantees**: the reference target and hidden tests are
> secret-bound (HMAC-derived; the public seed alone cannot recover them), the
> solver-visible challenge never contains verifier material, the active
> evaluator secret is never written into the solver-readable experiment DB, and
> a secret-bound challenge commits to its verifier material so the verifier can
> reject a wrong secret before any hidden evaluation.
> What it does **not** guarantee: an agent with the verifier-private path or the
> secret itself can still recover hidden material, so adversarial evaluation
> MUST run the solver in a workspace that excludes the verifier-private state.

---

## Challenge Families

| Challenge | Status | Purpose |
|-----------|--------|---------|
| CSP-v0.1 | Baseline | Infrastructure validation |
| SYNTH-v0.1 | Experimental | Program-synthesis research |
| OPT-v0.1 | Experimental | Continuous solution quality |
| REPO-v0.1 | Stable | Agent Benchmark — workspace + patch verification |

Difficulty levels are **preset parameter packs**, not claims of scientifically
calibrated universal difficulty.

---

## Agent Benchmark (REPO-v0.1)

VICA v0.3 can evaluate **coding agents** — not just algorithms and structured
answers. A REPO challenge gives an agent a small Python repository and a task;
the agent edits the workspace and VICA captures the edits as a git diff (patch),
then verifies them deterministically against public + hidden tests.

Controls ensure research validity:

- NoOp baseline (empty patch) must fail hidden tests — no task is vacuously
  passable.
- Reference baseline (authoritative patch) must pass 100%.
- Hidden tests are secret-derived and never shipped to the agent.
- Strict reverify binds `workspace_hash` + `patch_hash` so tampered results are
  caught.

See `docs/challenge-research/repo/` for the threat model, shortcut audit, task
validity, and difficulty calibration. This is a **local** runner; the sandbox is
experimental local process isolation, not hardened hostile-code isolation.

---

## Benchmarks

Historical / engineering-validation results are kept for provenance. They are
**not** framed as final leaderboards:

- `docs/reports/csp-v0.1-first-run.md` — CSET Random vs Z3 (infrastructure validation).
- `docs/reports/synth-v0.1-scale.md` — SYNTH random vs brute (engineering validation;
  predates verifier-secret hidden-material isolation; uses the historical
  generator `0.1.0` — the current post-isolation generator is `0.2.0`).
- `docs/reports/opt-v0.1-scale.md` — OPT baselines with exact DP reference.

Reports predating the hidden-material isolation explicitly disclose that they are
not adversarial public benchmarks.

---

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,solver]"

vica --help
vica version
vica benchmark --challenge csp-v0.1 --difficulty 1-3 --systems random,z3 --instances 1000 --seed 42
vica report <experiment-id>
```

The default database lives at `.vica/vica.db` (gitignored), so a fresh clone does
not accumulate runtime artifacts in the repo root.

### External Evaluation (REPO Agent Benchmark)

```bash
# 1. Prepare an Evaluation Bundle (public + private) for a REPO challenge.
vica eval prepare --challenge repo-v0.1 --difficulty 1-3 --instances 24 --seed 42 --out ./bench \
  --verifier-secret "$VICA_VERIFIER_SECRET"

# 2. Run a coding agent once per challenge (edits the workspace; VICA captures the patch).
vica agent run --bundle ./bench/public --command "codex ..." --out ./subs --system my-agent

# 3. Baselines: NoOp must fail hidden; Reference must pass.
vica agent noop      --bundle ./bench/public --out ./subs-noop
vica agent reference --bundle ./bench/public --out ./subs-ref --verifier-secret "$VICA_VERIFIER_SECRET"

# 4. Authoritatively verify a submission and write a Result Bundle.
vica eval verify --evaluation ./bench --submission ./subs --out ./results --verifier-secret "$VICA_VERIFIER_SECRET"

# 5. Strictly reverify the Result Bundle (no solver call).
vica reverify ./results --evaluation ./bench --verifier-secret "$VICA_VERIFIER_SECRET"
```

> The agent's environment defaults to a safe allowlist. Forward a solver's own API
> key explicitly with `--pass-env OPENAI_API_KEY`. Verifier-reserved secrets are
> never forwarded, even if requested.

---

## Documentation

- [Vision](docs/VISION.md)
- [Protocol & Technical Specification](docs/SPEC.md)
- [Benchmark Methodology](docs/BENCHMARK_METHODOLOGY.md)
- [Bundle Formats](docs/protocol/BUNDLE.md)
- [Roadmap](docs/ROADMAP.md)
- [Implementation Tasks](docs/TASKS.md)
- [Challenge Research Lab](docs/challenge-research/README.md)
- [REPO-v0.1 Research Lab](docs/challenge-research/repo/README.md)
- [Changelog](CHANGELOG.md)
- Experiment reports: `docs/reports/`

---

## License

Apache License 2.0. See [LICENSE](LICENSE).