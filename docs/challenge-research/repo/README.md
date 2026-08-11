# REPO-v0.1 — Agent Benchmark Challenge Family

> Status: **v0.3.0 Released** — the REPO-v0.1 Agent Benchmark works end-to-end
> (workspace identity, patch candidate, hidden verifier, Agent runner, NoOp /
> Reference controls, strict reverify). Scientific difficulty calibration is
> *structural*; agent-performance calibration is `Not Yet Established` (no real
> coding agent was available to measure).

## 1. What REPO-v0.1 measures

REPO-v0.1 evaluates a computation system's ability to produce a correct,
verifiable, re-verifiable software modification to a small, previously-unknown
Python repository under a limited time budget and unknown hidden tests.

The unified research question (docs/SPEC.md "REPO-v0.1"):

> Given a small code repository and a task, can a system produce a correct patch
> that passes both public and hidden verification?

## 2. Task kinds (`task_kind`)

| task_kind | meaning | templates |
|-----------|---------|-----------|
| `repair` | fix a real bug, keep the interface, pass public + hidden verifier | `cache`, `parser`, `state_machine`, `storage` |
| `implementation` | fill in a TODO / incomplete behavior without breaking existing behavior | `scheduler`, `serialization` |

## 3. Component model

```text
Workspace (small Python repo)   →  Patch Candidate (git unified diff)
   ├─ solution.py                     ├─ captured by the Agent runner
   ├─ tests/test_public.py            ├─ bounded (MAX_PATCH_BYTES / files / lines)
   └─ task.md                         └─ re-appliable, hashable, auditable
```

- **Workspace identity** = SHA-256 of the canonical sorted manifest of
  (relative path, file bytes SHA-256, mode). Excludes `.git/`,
  `__pycache__/`, caches, `build/`, `dist/`. See `src/vica/repo/workspace.py`.
- **Workspace safety** rejects absolute paths, `..`, symlink escape, device /
  FIFO / socket files, and nested `.git` (embedded repos). A root `.git` is the
  workspace's own repo dir and is excluded from identity.
- **Patch artifact** is a git unified diff. It is the formal protocol object:
  small, auditable, savable, replayable, hashable, and third-party re-appliable.
  See `src/vica/repo/patch.py`.

## 4. Secret-bound verification

Reference (fixed) source and hidden test cases are derived only from the
verifier secret (HMAC-SHA256, domain-separated tags), never from the public
`(seed, difficulty)` — the same secret-bound design as SYNTH-v0.1.

Public tests are inputs on which the buggy and fixed sources **agree** (a NoOp
patch passes them — the honest hint). Hidden tests are inputs on which they
**disagree** (a NoOp patch fails them — the discriminating negative control).

## 5. Verifier flow

```text
authoritative pristine workspace → validate workspace hash → validate patch →
materialize to a fresh temp dir (never the original) → apply patch →
structural constraints → public tests → secret-derived hidden tests →
deterministic result
```

Untrusted patched code runs in the `vica.sandbox` subprocess (resource limits,
minimal env, clean cwd, bounded output). We call `solve` directly rather than
pytest so pytest-discovery / skip shortcuts cannot turn a failure into a pass.

## 6. Controls

- **NoOp baseline** (`vica agent noop`): submits an empty patch. Must fail the
  hidden verifier for every released task (§40).
- **Reference baseline** (`vica agent reference`): submits the authoritative
  patch. Must pass 100% (§41). Evaluator/calibration only — never shipped to
  solvers.
- **Public-only probe**: a naive repair that satisfies public tests but fails
  hidden tests validates that hidden tests add discriminative power (§42).

## 7. Validation summary (generator `0.1.0`, 120-instance survey)

| metric | value |
|--------|-------|
| templates | 6 |
| task kinds | `repair` (4), `implementation` (2) |
| instances surveyed | 120 (40 seeds × difficulties 1–3) |
| distinct workspace hashes | 100 |
| reference pass | 120 / 120 |
| NoOp hidden-fail | 120 / 120 |
| hidden case counts | d1=6, d2=10, d3=14 |

See `threat-model.md`, `shortcut-audit.md`, `task-validity.md`, and
`difficulty-calibration.md` for the detailed analysis.

## 8. Related documentation

- `docs/SPEC.md` — Protocol & Technical Specification (REPO sections)
- `docs/challenge-research/repo/` — this family's research lab
- `src/vica/repo/` — generator, patch, templates, workspace, family
- `tests/test_repo.py` — REPO-v0.1 test suite