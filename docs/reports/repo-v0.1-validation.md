# REPO-v0.1 Validation Report

> Status: **v0.4.0** — generated from a real reproducibility run using the
> current generator `0.1.0`. Only measured data is reported; anything not
> measured is explicitly `Not Measured`.

## 0. v1.0 release-gate run (formal Task Pack `repo-v0.1-core`)

A separate 24-instance run meets the v1.0 formal Task Pack gate
(`docs/SPEC.md` §104–§105):

- Task Pack: `repo-v0.1-core` (version `1`), evaluation `eval-6696596c7378`
- Generator `repo-v0.1` `0.1.0`, seed `11`, difficulties 1–3, 8 instances each
- Template coverage across 24 instances: all **6** templates present
  (`parser` 7, `serialization` 6, `state_machine` 6, `cache` 2, `scheduler` 2,
  `storage` 1)
- Reference (positive control): **24 / 24 pass**
- NoOp (negative control): **0 / 24 pass**
- Reverify: **24 / 24 matched**, identical valid/score/error semantics
- Result Bundles bind `task_pack_id` / `task_pack_version` / `task_pack_hash`

## 1. Run provenance

- Task Pack: `repo-v0.1-core` (version `1`)
- Task Pack hash: `01b23d24ce6c498d48fcf3f0951c7ea88a444b866d1e995c72c99123661a57b5`
- Generator: `repo-v0.1` `0.1.0`, seed `11`, difficulties 1–3, 4 instances each
- Verifier: deterministic, secret-bound hidden tests (no LLM judge)
- Backend: `local` (stable)

## 2. Benchmark composition

| metric | value |
|--------|-------|
| challenges | 12 |
| templates | 5 observed (`cache`, `parser`, `serialization`, `scheduler`, `state_machine`) |
| task kinds | `repair` 7, `implementation` 5 |
| difficulty distribution | d1=4, d2=4, d3=4 |

## 3. Controls

| control | outcome |
|---------|---------|
| Reference patch (positive control) | 12 / 12 pass |
| NoOp patch (negative control) | 0 / 12 pass (hidden verifier discriminates) |
| Shortcut probes | rejected as solver outcomes (see `shortcut-audit.md`) |
| Public-only / incomplete patch | hidden tests add discriminative power (§42) |
| Public-only overfit probe (§77) | every template's naive state passes public but fails hidden |
| Seed generalization (§78) | different seeds → different hidden data; reference still passes |

## 4. Reverify consistency

| metric | value |
|--------|-------|
| reverify matched | 12 / 12 |
| reverify status | identical valid/score/error semantics |
| Task Pack binding | enforced (tampered hash refused) |

## 5. Reproducibility binding

- Result Bundle records `task_pack_id`, `task_pack_version`, `task_pack_hash`
  and an Execution Profile (environment provenance, env **names only**).
- Strict reverify binds the Task Pack hash, workspace hash, patch hash,
  challenge id, generator version, and verifier-material commitment.

## 6. Agent performance

- External coding-agent empirical calibration: **Not Measured** (no real agent
  was run). No model success rates are reported or implied.
- Difficulty calibration is **structural** (workspace complexity, file count,
  hidden-case count); agent-performance monotonicity is **not claimed**.

## 7. Honest claims

- REPO task-verifier validity: **Established to current tests**.
- Shortcut resistance: **Established against enumerated probes**.
- Universal coding-agent difficulty: **Not claimed**.
- Real commercial-agent ranking: **Only if measured** (not here).
- Hardened hostile-code isolation: **Not claimed** (experimental local
  process isolation only).