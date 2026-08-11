# SYNTH-v0.1 Generalization

> Status: **Partially established** — the design intent and the public/hidden
> separation are in place; a quantitative hidden-generalization measurement
> under the current `0.2.0` generator is `Not Yet Established`.

## 1. What "generalization" means here

SYNTH gives a solver 10 public `(input -> expected)` examples and asks for a
program that also matches the hidden tests. The reference target and hidden
tests are secret-bound:

```text
target_seed = HMAC-SHA256(verifier_secret, type:version:target:seed:difficulty)
hidden_seed = HMAC-SHA256(verifier_secret, type:version:hidden:seed:difficulty)
```

The `target` and `hidden` tags are domain-separated, so the two RNG streams
never overlap. A solver holding only the public `(seed, difficulty)` cannot
derive either.

## 2. What the challenge is intended to measure

Two competing hypotheses:

```text
H1  The public examples pin down the target uniquely-ish.
    => SYNTH measures reverse-engineering / search.

H2  Many distinct programs fit the public examples.
    => SYNTH measures inductive bias / generalization (the intended signal).
```

The current design is built around H2: the brute-force baseline finds the
*first* public-passing program, which often fails hidden tests (overfit). This
is the intended generalization signal — but it must be quantified.

## 3. Established

- The public/hidden/secret separation is implemented and tested
  (`docs/SPEC.md` §14bis; `test_synth_generator.py`).
- The historical scaled run (`0.1.0`) showed brute-force overfit on public
  tests: candidates that pass all public examples frequently fail hidden ones.
- The budget is `code_size=200` tokens, `max_eval_ms=10`, so a solver must
  produce a compact program, not a lookup table enumerating all inputs.

## 4. Ambiguity probe (established)

The ambiguity probe (`scripts/analyze_synth_ambiguity.py`) counts distinct
programs within budget that fit all 10 public examples. On the current `0.2.0`
generator (seed=42, random secret) the count exceeds the enumeration cap
(>20001) even at d1 — see `shortcut-audit.md` §4. This establishes that the
public examples are **highly ambiguous**: many distinct programs fit them, so
SYNTH measures inductive bias / generalization. Hidden tests are what separate
methods that pass public examples.

## 5. Hidden generalization (partially established)

- The historical scaled run (`0.1.0`) showed brute-force overfit on public
  tests: candidates that pass all public examples frequently fail hidden ones.
- Combined with the ambiguity probe, the mechanism is clear: with many
  publicly-consistent programs, hidden tests carry the discriminating signal.
- **However**, a quantitative gap (valid-on-public vs valid-on-hidden rates)
  has **not yet been re-measured** under the current `0.2.0` generator.

> Hidden-generalization gap on the current generator: `Not Yet Established`.

## 6. Conclusion

The mechanism for measuring generalization is present, and the ambiguity probe
confirms the public examples are highly ambiguous under the current generator.
The quantitative hidden-generalization gap (valid-on-public vs valid-on-hidden)
is the highest-value next calibration step before SYNTH can support comparative
research claims.