# VICA Challenge Research Lab

> Location: `docs/challenge-research/`
>
> The research home for each challenge family. The lab's job is to **attack**
> each challenge and answer, honestly:

```text
What does this challenge actually measure?
Is there a shortcut?
Does a specialized solver dominate?
Is the difficulty preset trustworthy?
Is the result stable?
Does failure come from reasoning or from formatting?
```

The lab records findings even when they are negative. A challenge that is
trivially defeated by a specialized solver is a research result, not a failure.

## Principles

1. **No fabricated conclusions.** When a claim is not yet established by
   data, it is written as `Not Yet Established` — never invented to make the
   project look better.
2. **Engineering validation ≠ scientific benchmark.** A 5-instance smoke test
   is not evidence that "Agent A beats Agent B". Research claims require
   sample counts, seeds, systems, VICA commit, and experiment purpose.
3. **Provenance is mandatory.** Every recorded number names its generator
   version, seed, sample size, and systems.
4. **Difficulty must be attacked, not tuned to fit.** A non-monotonic curve is
   recorded and analyzed, not silently re-fit.

## Structure

```text
docs/challenge-research/
├── README.md
├── synth/          # SYNTH-v0.1 (flagship research challenge)
│   ├── shortcut-audit.md
│   ├── difficulty-calibration.md
│   ├── generalization.md
│   └── solver-dominance.md
└── opt/            # OPT-v0.1 (quality-metric research challenge)
    └── README.md
```

## Calibration tooling

- `scripts/calibrate_synth.py` — SYNTH d4/d5 difficulty calibration harness
  (target node-count distribution, constant-rate, brute-force success through
  hidden tests).
- `scripts/analyze_synth_ambiguity.py` — SYNTH target-complexity + ambiguity
  probe (AST depth / node count / operator count per difficulty, plus the
  count of publicly-consistent programs).
- `scripts/llm_find.py` / `llm_probe.py` / `llm_verify.py` — LLM-style
  exploration tooling (short-expression induction; not a real LLM benchmark).

## Research integrity cross-references

- Statistical / reporting method: `docs/BENCHMARK_METHODOLOGY.md`
- Bundle & verification protocol: `docs/protocol/BUNDLE.md`
- Verifier-material boundary: `docs/SPEC.md` §14bis / §17
- SYNTH generator design: `docs/reports/synth-v0.1-design.md`
- SYNTH v0.2 exit criteria (GO / PIVOT / NO-GO): `docs/BENCHMARK_METHODOLOGY.md` §14