# Changelog

All notable protocol changes to VICA are recorded here. Entries are concise and
focus on protocol-level changes, not development churn.

## 1.0.1 — Research Integrity Hotfix (2026-08-12)

**Research-integrity fix for the REPO-v0.1 Agent Benchmark plus protocol
consistency.**

### Fixed

- **Process-separated REPO candidate verification** (`src/vica/repo/family.py`):
  candidate `solve` runs in an isolated subprocess that receives only the case
  inputs; the parent evaluator owns the expected values, so candidate frames can
  never inspect or monkeypatch them. Closes the v1.0.0 hidden-expected
  interpreter-leak bypass.
- **Static reference-source leakage removed** (`src/vica/repo/templates.py`):
  the public `fixed`/reference source is no longer reachable through a
  secretless public API; authoritative reference material now requires the
  verifier secret.
- **REPO generator `0.1.0 → 0.2.0`** (`src/vica/repo/generator.py`): seed now
  genuinely varies the solver-visible code instance (not just hidden cases),
  and reference material is secret-bound.
- **Historical `0.1.0` semantics withdrawn**: v1.0.0 generator/verifier
  semantics are not silently re-interpreted under 0.2.0; historical results are
  marked withdrawn and authoritative reverify under the old semantics is refused.
- **Task Pack `1 → 2`** (`src/vica/eval/taskpack.py`): dynamic REPO evaluations
  are now `repo-v0.1-generated` (the `core` id is reserved for a truly frozen
  pack).
- **v2 workspace integrity inspection** (`src/vica/eval/bundle.py`):
  `vica eval inspect` validates `public/workspaces/` (existence, symlink safety,
  hash, manifest, set consistency).
- **Strict bundle-version pairing** (`dispatch.py`/`submission.py`/`reverify.py`):
  Evaluation v1 ↔ Submission v1 ↔ Result v1 and v2 ↔ v2 ↔ v2 only; cross-version
  matches are an `EvaluationFailure`.
- **Study result persistence** (`src/vica/eval/study.py`): per-replicate
  `submission/` and `result/` bundles persist after the study returns, with
  portable relative paths and full provenance.
- **Study task/template layered metrics**: `by_task_kind` and `by_template`
  (with `by_difficulty`) are now accumulated from Result records.
- **Family-scoped Task Pack version** (`src/vica/eval/taskpack.py`): the pack
  version is now keyed per challenge family — only REPO-v0.1 (whose
  generator/verifier semantics changed) is `2`; CSP/SYNTH/OPT keep the default
  `1`. A bump no longer silently re-identifies unrelated families.
- **Strict reverify binds `task_pack_version`** (`src/vica/eval/reverify.py`):
  the semantic layer now also rejects a tampered pack version, so a forged
  `task_pack_version` fails even after the bundle hash is recomputed.
- **Strict `system_id` validation** (`src/vica/eval/study.py`): a provenance
  `system_id` must be a single safe `[A-Za-z0-9._-]` path component; ambiguous
  or colliding ids are rejected with `ValueError` instead of being lossily
  normalized onto a shared on-disk run path.

### Maturity (final freeze audit)

- **REPO-v0.1 downgraded to Experimental.** The public `Template.builder`
  remains enumerable, so holding the public `solution.py` + template name +
  installed public VICA package lets an attacker recover the exact reference
  source (empirically confirmed on `parser`). Per research-integrity policy this
  is **not** masked by HMAC / random variables / private naming. Exact-reference
  lookup resistance is marked **Not Yet Established** until a
  semantic-oracle verifier (or another genuinely lookup-free design) is
  independently audited. VICA Framework 1.0.1 itself stays **Stable**.

### Notes

- v1.0.0 REPO generator `0.1.0` was withdrawn for adversarial benchmark use
  because candidate execution shared the verifier interpreter and allowed
  verifier-frame expected-value access. This is a benchmark research-integrity
  flaw — not a hardened-host sandbox escape claim.
- No `v1.0.1` tag or Release is created in this round; the branch awaits
  independent audit.

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