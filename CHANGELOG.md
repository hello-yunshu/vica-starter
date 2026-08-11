# Changelog

All notable protocol changes to VICA are recorded here. Entries are concise and
focus on protocol-level changes, not development churn.

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