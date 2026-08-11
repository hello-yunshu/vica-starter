# SYNTH-v0.1 Solver Dominance

> Status: **Historical data only** — baseline separation was validated on the
> `0.1.0` generator. No real-LLM comparison exists yet; the current `0.2.0`
> generator has no solver-dominance measurements.

## 1. Objective

Determine whether a specialized / brute-force solver or a trivial baseline
trivially collapses all difficulties, which would make SYNTH useless for
measuring general-purpose reasoning.

## 2. Historical baselines (generator 0.1.0, seed=42, n=200/difficulty)

| System | d1 | d2 | d3 | d4 | d5 |
|--------|----|----|----|----|----|
| synth-brute | 100% | 65.5% | 47.5% | 23.0% | 11.0% |
| synth-random | 81% | 33.5% | 16% | 7.5% | 2.0% |

(Run data: `docs/reports/synth-v0.1-scale.md`; d4/d5 numbers are the calibrated
values.)

Interpretation:

- Brute-force does **not** trivially collapse all difficulties: it drops from
  100% to 11% across d1–d5.
- Random is close to floor at high difficulty (2%), indicating the search space
  is genuinely hard for uninformed methods at d5.
- There is meaningful separation between brute and random (≈2–3× at d3), which
  is the minimum needed for a useful benchmark.

## 3. LLM / specialized dominance (Not Yet Established)

- No real-LLM numbers exist. The real API paths (`llm-one-shot`, `llm-agent`)
  are implemented but require a configured key.
- The historical `llm-short` comparison (which claimed an LLM-style heuristic
  beat brute) was **invalidated**: it was built on the pre-isolation `0.1.0`
  target and does not apply to the current secret-bound `0.2.0` verifier. See
  `docs/reports/synth-v0.1-llm.md` "research-integrity disclosure".
- Whether a specialized solver (e.g. a symbolic / enumerative one) trivially
  dominates the current generator is **not yet measured**.

> Status: `Not Yet Established`.

## 4. Symbolic / specialized baseline feasibility note

SYNTH programs are pure integer expressions over a small operator set. It is
plausible to encode them as a symbolic constraint problem (finite-domain
synthesis). A feasibility prototype is out of scope for v0.2 delivery, but if a
specialized solver later collapses the current difficulties, that is a valid
**research result** signalling a PIVOT (per `docs/BENCHMARK_METHODOLOGY.md`
§14), not a project failure.

## 5. Conclusion

- No trivial baseline collapses all difficulties in the historical data.
- Real-LLM and specialized-solver dominance are **unmeasured** for the current
  generator. These measurements gate the GO / PIVOT / NO-GO decision.