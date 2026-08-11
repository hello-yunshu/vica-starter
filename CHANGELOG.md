# Changelog

All notable protocol changes to VICA are recorded here. Entries are concise and
focus on protocol-level changes, not development churn.

## 1.0.0 — Research Benchmark Stable (2026-08-12)

**Protocol + benchmark surface frozen. Freeze / compatibility / release.**

- **Protocol stable surface**: Challenge, Candidate, Result, Evaluation /
  Submission / Result Bundle v1+v2, Workspace, Patch Candidate, Task Pack,
  Execution Profile, Strict Reverify.
- **Stable CLI**: `vica version / benchmark / report / eval prepare|inspect|
  verify / solver run / agent run|noop|reference / reverify / study run`; CLI
  UX audited (help text, path semantics, error messages).
- **Compatibility contract** (`docs/SPEC.md`): v1/v2 Bundle reading, Challenge
  identity, canonical serialization, verifier authority, UNKNOWN cost
  semantics, material commitment, Result integrity, strict reverify all
  **Stable**; SYNTH/OPT science, OS sandbox, Docker backend, agent-performance
  calibration remain **Experimental**.
- **Formal REPO Task Pack** `repo-v0.1-core`: ≥6 templates, ≥24 reproducible
  instances, repair + implementation, difficulty 1–3; every released instance
  passes reference, fails NoOp, reproduces workspace hash, and reverifies.
- **Release docs**: `docs/MIGRATION.md`, `SECURITY.md`; README v1.0 status.
- **Packaging**: wheel + sdist build, fresh-venv install smoke (`vica version`,
  `vica --help`, minimal CSP + REPO verify/reverify).
- Platform: Linux + macOS supported; Windows not supported in v1.0. PyPI
  publication not configured.

## 0.4.0 — Benchmark Validation & Reproducibility (2026-08-12)

**Reproducibility & validation layer over the v0.3 Agent Benchmark.**

- **Task Pack**: stable, versioned identity of a benchmark instance set
  (`task_pack_id` / `task_pack_version` / `task_pack_hash`). Result Bundles
  record all three; strict reverify binds the hash so a tampered result set is
  refused even when valid/score coincide.
- **Execution Profile**: Result Bundles record environment provenance (runner
  backend, OS/arch, Python version, dependency-env hash, VICA version, git
  commit, runtime policies, forwarded env **names**). Secret values are never
  recorded.
- **Study**: `vica study run` — multi-system × task × replicate nested loop
  (no DAG/job queue) with aggregated success rate + Wilson CI, latency,
  failure taxonomy, and per-difficulty metrics. Replicates are run identity,
  never Challenge identity.
- **Golden compatibility fixtures** under `tests/fixtures/protocol/`
  (Bundle v1 + v2) so 1.0 can still load and reverify historical artifacts.
- **Benchmark validation**: reference positive control, NoOp negative control,
  public-only overfit probe, and seed-generalization checks.
- New docs: `docs/REPRODUCIBILITY.md`, `docs/reports/repo-v0.1-validation.md`;
  threat-model updated with Execution provenance.

## 0.3.0 — Agent Benchmark (2026-08-12)

**New: REPO-v0.1 Agent Benchmark.**

- New `repo-v0.1` challenge family: a small Python workspace with a task; the
  candidate is a git unified-diff **patch artifact**.
  - `Workspace` object with a canonical identity hash (`workspace_hash`) and
    workspace safety checks (reject absolute paths, `..`, symlink escape,
    device/FIFO/socket, nested `.git`).
  - `PatchCandidate`: small, auditable, savable, replayable, hashable patches,
    bounded by `MAX_PATCH_BYTES` / `MAX_CHANGED_FILES` / `MAX_CHANGED_LINES`.
  - 6 task templates (`parser`, `cache`, `state_machine`, `serialization`,
    `scheduler`, `storage`) across `repair` and `implementation` task kinds.
  - Secret-bound hidden verification: reference patch and hidden tests are
    derived from the verifier secret (HMAC-SHA256, domain-separated), never the
    public `(seed, difficulty)`.
- **Evaluation/Submission/Result Bundle v2**, routed by a Bundle dispatcher so
  v1 artifacts are still read with the v1 reader (no silent reinterpretation).
- **Agent Mode**: `vica agent run / noop / reference`.
  - NoOp baseline (empty patch) and Reference baseline (authoritative patch).
  - Explicit `--pass-env` forwarding; verifier-reserved secrets are always
    rejected.
- **REPO verifier** runs patched code in the sandbox (never the original
  workspace), with structural constraints, public tests, and secret-derived
  hidden tests. New failure taxonomy includes `PATCH_APPLY_FAILURE`,
  `STRUCTURAL_VIOLATION`, `PUBLIC_TEST_FAILURE`, `HIDDEN_TEST_FAILURE`.
- **REPO strict reverify** binds `workspace_hash` + `patch_hash` so tampered
  results are detected.
- New research lab docs under `docs/challenge-research/repo/`.

## 0.2.0 — Benchmark Research & External Evaluation

- Portable Evaluation / Submission / Result Bundles (v1).
- External File Exchange and External Command Solver.
- SYNTH-v0.1 secret-bound generator (`0.2.0`), CSP-v0.1, OPT-v0.1.
- Authoritative deterministic verifier; strict reverify; Result integrity.
- Failure taxonomy; Wilson CI; cost coverage; paired comparison.
- Challenge Research Lab.

## 0.1.0 — Protocol Core

- Frozen protocol core: Challenge / Candidate / Result.
- Deterministic verification; canonical serialization; verifier-material
  commitment; challenge identity; secret isolation.