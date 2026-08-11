# REPO-v0.1 Task Validity

> Status: **Established to current tests** — every released task satisfies the
> positive / negative controls and the seed-generalization property on the
> current `0.1.0` generator.

## 1. Validity criteria

For every released REPO-v0.1 instance, the following must hold (§105):

```text
Reference passes        reference patch → 100% pass
NoOp fails              empty patch → fails the hidden verifier
Workspace reproducible  workspace hash is deterministic
Public/private no leak  hidden tests + reference never in the public bundle
Reverify identical      strict reverify reproduces the stored result
```

## 2. Empirical survey (generator `0.1.0`)

A 120-instance survey (40 seeds × difficulties 1–3) ran the family verifier
directly on the authoritative challenge (with the verifier secret) and
classified each outcome:

| metric | result |
|--------|--------|
| reference pass | 120 / 120 (100%) |
| NoOp hidden-fail | 120 / 120 (100%) |
| distinct workspace hashes | 100 / 120 |
| hidden case counts | d1=6, d2=10, d3=14 |

- **Reference pass 100%** confirms the reference patch is a valid positive
  control (§41).
- **NoOp hidden-fail 100%** confirms no task is vacuously passable; every task
  has hidden tests that the buggy source fails (§40).
- Different seeds produce different hidden test sets (seed generalization), so
  a task's semantics are stable while its concrete instances differ.

## 3. Seed generalization

Hidden tests for the same difficulty but different seeds differ, and the
workspace / challenge identity changes while task semantics are preserved
(§78). This is enforced by the secret-bound, domain-separated RNG
(`_public_rng` vs `_secret_rng(hidden)`) in `src/vica/repo/generator.py`.

## 4. No vacuously-passable tasks

Because public tests are inputs where buggy == fixed (a NoOp patch passes them)
and hidden tests are inputs where buggy != fixed (a NoOp patch fails them), the
construction guarantees, for every task:

```text
NoOp        → passes public, fails hidden
Reference   → passes public + hidden
public-only → passes public, fails hidden (the public-only overfit probe)
```

## 5. Caveat

Task-verifier validity is established to the current tests. It is not a claim
of universal coding-agent difficulty (see `difficulty-calibration.md`).