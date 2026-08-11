# SYNTH-v0.1 Shortcut Audit

> Status: **Partial** — public-ambiguity and constant/trivial-target shortcuts are
> documented; a systematic brute-force ambiguity probe is `Not Yet Established`
> for the current secret-bound generator `0.2.0`.

## 1. What this audit checks

```text
1. Does public ambiguity alone allow a memorization / copy shortcut?
2. Can a trivially small or constant target be solved by copying an output?
3. Does enumerating within budget find programs that fit all public tests but
   fail hidden tests (overfit)?
4. Is there a DSL-level exploit (e.g. bignum, eval-step, parse-depth)?
```

## 2. JS-enabled shortcuts (established)

The DSL interpreter is restricted (no `exec`, no `eval`, no loops, no side
effects). Interpreter-level guards are deterministic and map to
`sandbox_error`:

```text
MAX_PROGRAM_CHARS   1 MiB      program-length cap
MAX_TOKENS          4096       hard token cap
MAX_PARSE_DEPTH     96         parse nesting cap
MAX_EVAL_STEPS      200_000    eager step cap
MAX_INT_BITS        65536 bit  any intermediate/result above this is a guard hit
```

These are documented in `src/vica/challenges/synth_v01/family.py` and tested in
`test_synth_generator.py`. This is **interpreter-level** sandboxing, not an OS
sandbox; it bounds resource abuse but is not a hardened isolation boundary.

## 3. Constant / trivial-target shortcut (established, mitigated)

Before difficulty calibration, d4/d5 added `abs` / `neg` to the operator pool,
which inflated the share of effectively-constant or tiny targets (e.g.
`0 * 13`, `abs(15)`). Such targets are solvable by copying a single output and
carry no reasoning. This made brute-force success rebound above d3.

Mitigation (in `DIFFICULTY_PRESETS` for d4/d5):

```text
min_nodes        d4=5 / d5=7   reject targets below a node-count threshold
reject_constant  True          reject targets constant over 16 random inputs
```

See `docs/challenge-research/synth/difficulty-calibration.md` for the before /
after numbers.

## 4. Public-example ambiguity (established, v0.2 generator)

The reference target and hidden tests are secret-bound
(`HMAC-SHA256(verifier_secret, ...)`, domain-separated `target` / `hidden`
tags). A solver holding only the public `(seed, difficulty)` cannot reconstruct
them.

The ambiguity probe (`scripts/analyze_synth_ambiguity.py`) enumerates distinct
programs within budget that fit all 10 public examples and reports
`number_of_publicly_consistent_programs`. Initial probe on the current `0.2.0`
generator (seed=42, random secret):

```text
d1  target='-11 - x'       ambiguity >= 20001 programs (capped)
d1  target='-11 + x'       ambiguity >= 20001 programs (capped)
d2  target='-17 + x + x*x' ambiguity >= 20001 programs (capped)
d2  target='x + -1 + -12'  ambiguity >= 20001 programs (capped)
```

Even at d1 the public examples do **not** pin the target down uniquely — the
count exceeds the enumeration cap. This confirms the challenge measures
**inductive bias / generalization**, not unique reverse-engineering. That is
allowed, but it means SYNTH primarily differentiates methods by their search /
induction quality, and the ambiguity must be acknowledged in any claim.

> Status: `Established` (probe; the method is reproducible).

## 5. Overfit behavior (established, historical)

The historical scaled run (`docs/reports/synth-v0.1-scale.md`, generator
`0.1.0`) showed the brute-force baseline finding the *first* public-passing
program, which frequently failed hidden tests. This is the intended
generalization signal, but it must be re-measured under the current `0.2.0`
secret-bound generator before any claim about the current generator.

## 6. Conclusion

- Interpreter-level resource guards are in place and tested (`SANDBOX_ERROR`).
- Constant/trivial-target shortcut is mitigated by calibration filters.
- A systematic ambiguity probe for the current generator is **not yet
  established** — recommended next step before claiming SYNTH measures
  generalization robustly.