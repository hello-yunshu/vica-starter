# REPO-v0.1 Validation Report

> Status: **v1.0.2** — measured facts from the v1.0.1 reproducibility run using
> generator `0.2.0` (process-separated verification), now supplemented by the
> **semantic-oracle verifier** (generator `0.3.0`, §1.6) that closes the
> reference-source lookup. Only measured data is reported; anything not
> measured is explicitly `Not Measured`.

## 0. Historical v1.0.0 validation — Withdrawn for adversarial interpretation

The v1.0.0 validation below was generated with REPO generator `0.1.0`, whose
candidate execution shared the verifier interpreter and allowed
verifier-frame expected-value access (a benchmark research-integrity flaw).
For adversarial benchmark interpretation it is **withdrawn**:

```text
Historical v1.0.0 validation
Withdrawn for adversarial interpretation
```

It is retained for provenance only and is **not** compared or merged with any
`0.2.0` result. The historical run reported:

- Task Pack `repo-v0.1-core` (version `1`), generator `0.1.0`, 24 instances
  across all 6 templates
- Reference (positive control): **24 / 24 pass**
- NoOp (negative control): **0 / 24 pass**
- Reverify: **24 / 24 matched**

These numbers used the old verifier semantics and must not be re-used as an
adversarial benchmark claim.

---

## 1. v1.0.1 validation (generator `0.2.0`, Task Pack v2)

A fresh 24-instance run using the new generator `0.2.0` and Task Pack v2
(`repo-v0.1-generated`) with adversarial research-integrity controls.

### 1.1 Run provenance

- Generator: `repo-v0.1` `0.2.0`, seed `11`, difficulties 1–3, 8 instances each
- Task Pack: `repo-v0.1-generated` (version `2`)
- Verifier: deterministic, secret-bound hidden tests (no LLM judge)
- Candidate execution: **process-separated** (candidate receives only inputs;
  expected values stay in the parent evaluator)
- Backend: `local`

### 1.2 Benchmark composition

| metric | value |
|--------|-------|
| challenges | 24 |
| templates | all **6** present (`parser` 7, `serialization` 6, `state_machine` 6, `cache` 2, `scheduler` 2, `storage` 1) |
| difficulty distribution | d1=8, d2=8, d3=8 |

### 1.3 Controls (real measured)

| control | outcome |
|---------|---------|
| Reference patch (positive control) | **24 / 24 pass** |
| NoOp patch (negative control) | **0 / 24 pass** (hidden verifier discriminates) |
| Adversarial frame-stealer (`inspect.currentframe` expected-value probe) | **0 / 24 pass** (process isolation blocks the exploit) |
| Wrong-secret probe | rejected (commitment mismatch) |
| Public-only overfit probe | public passes, hidden fails |
| Workspace / patch tamper | rejected (hash + manifest binding) |

### 1.4 Reverify consistency

| metric | value |
|--------|-------|
| strict reverify matched | **24 / 24** |
| reverify status | identical valid/score/error semantics |
| Bundle version pairing | v2 ↔ v2 ↔ v2 enforced (cross-version refused) |
| Task Pack binding | enforced (tampered hash refused) |

### 1.5 Reproducibility binding

- Result Bundle records `task_pack_id`, `task_pack_version`, `task_pack_hash`
  and an Execution Profile (environment provenance, env **names only**).
- Strict reverify binds the Task Pack id + version + hash, workspace hash,
  patch hash, challenge id, generator version, and verifier-material
  commitment.

## 1.6 Reference-source lookup resistance — Closed (semantic oracle)

The public `Template.builder` (open source, installed in the published wheel)
enumerates a finite variant space. An attacker holding the **public
`solution.py`** + **template name** + **installed public VICA package** can sweep
that space, match `instance.buggy == solution.py`, and recover the exact
`instance.fixed` (reference) source. This was **empirically confirmed** at v1.0.1
on the `parser` template: the fixed source was recovered by enumerating only a
handful of probe seeds.

Per research-integrity policy we **do not** treat that as closed by HMAC / extra
random variables / private naming / obfuscation — those are not a security
boundary (docs/SPEC.md "Verifier material"). Instead, the **semantic-oracle
verifier** (Route A) is now implemented (generator `0.3.0`, v1.0.2): the
authoritative expected value for every template comes from an independent, pure
`input -> expected` oracle that is **public by design** (it *is* the task
specification), never from a recoverable `fixed` source. Because correctness is
pinned to the public spec, an attacker who recovers `instance.fixed` by
enumerating the open-source builder gains **no advantage** — fixing the workspace
to match the public oracle is the honest task. The reference-source lookup is
therefore **eliminated, not obfuscated** (see
`docs/challenge-research/repo/semantic-oracle.md`), and the maturity read is
updated:

```text
Reference-source lookup resistance:
Established (per-template semantic oracle, generator 0.3.0)

REPO-v0.1 maturity:
Established (semantic-oracle verifier)
```

Regression coverage: `test_classification_expected_comes_from_oracle`,
`test_oracle_matches_fixed_semantics`, `test_oracle_is_pure_function_of_input`,
`test_former_generator_020_denied_at_family`. VICA Framework 1.0.2 remains
**Stable**.

## 2. Agent performance

- External coding-agent empirical calibration: **Not Measured** (no real
  commercial coding agent was run). No model success rates are reported or
  implied — Codex / Claude / Aider / Gemini remain **Not Measured**.
- Difficulty calibration is **structural** (workspace complexity, file count,
  hidden-case count); agent-performance monotonicity is **not claimed**.
- Seed now genuinely varies the solver-visible code instance (not just hidden
  cases); the reference patch differs across seeds.

## 3. Honest claims

- REPO task-verifier validity: **Established to current tests** (generator
  `0.2.0`, process-separated verification).
- Process-boundary correctness: **Established to enumerated adversarial tests**
  (frame inspection / monkeypatch / module probing cannot reach expected).
- Shortcut resistance: **Established against enumerated probes**.
- Universal coding-agent difficulty: **Not claimed**.
- Real commercial-agent ranking: **Only if measured** (not here).
- Hardened hostile-code isolation: **Not claimed** (experimental local process
  isolation only; the candidate is process-separated from evaluator frames, but
  this is a verifier correctness boundary, not a hardened OS sandbox claim).