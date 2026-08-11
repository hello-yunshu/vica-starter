# VICA Benchmark Methodology (v0.2)

> Location: `docs/BENCHMARK_METHODOLOGY.md`
>
> How VICA turns the engineering benchmark into a **research benchmark**: the
> dimension set, the statistical reporting, the failure taxonomy, and the
> research-integrity guardrails. Bundle file formats are in
> `docs/protocol/BUNDLE.md`; the protocol-layer changes are in `docs/SPEC.md`
> §17. SYNTH-specific calibration lives in `docs/challenge-research/`.

## 1. Design principles

```text
1. Solver output is untrusted.
2. Correctness remains deterministic.
3. No LLM judge.
4. External solvers and built-in solvers enter the same verifier.
5. Public bundles never contain verifier secret / hidden tests / reference target.
6. Result bundles are independently reverifiable.
7. UNKNOWN cost stays UNKNOWN, never silently becomes 0.
8. Historical benchmark data is not quietly re-interpreted by new logic.
9. Changing a challenge generator's semantics requires a version bump.
10. A benchmark result may legitimately fail to support the hypothesis.
```

## 2. Reporting dimensions

There is **no single overall score**. Each dimension is reported independently:

```text
Correctness   binary success per challenge
Quality       continuous objective distance (OPT regret)
Cost          known-cost coverage + estimated_cost_usd
Latency       wall-time distribution
Failure       taxonomy of non-valid outcomes
Coverage      fraction of instances with a measurable cost
```

## 3. Success rate and confidence interval

Success rate is reported **with** sample count and a 95% confidence interval.
The binomial interval uses the **Wilson score interval** (implemented in the
standard library, no SciPy):

```text
success_rate = 0.72
95% CI = [0.63, 0.80]
n = 100
```

An empty cell (`0 samples`) reports `N/A`, never a degenerate interval.

## 4. Latency

At least mean / median (p50) / p95. No complex distribution modeling in v0.2.

## 5. Cost

Both aspects are reported:

```text
known cost coverage = known_cost_instances / all_instances
estimated_cost_usd  (only when pricing is configured; else UNKNOWN / null)
```

`N/A` cost is correct but does not tell the reader how much data carries a
cost, so coverage is reported alongside. `UNKNOWN` never becomes `0.0`.

## 6. Failure taxonomy

The report layer uses a status taxonomy that may differ from the protocol
`ErrorCode`:

```text
valid
invalid_solution
timeout
transport_error
provider_error
parse_error
no_candidate
no_submission
sandbox_error
internal_error
unsupported
```

The key distinction: `wrong answer` vs `no answer` vs `the evaluation was
misconfigured` are reported separately.

### 6.1 Evaluation-level vs solver-level errors

```text
Evaluation Failure (evaluator problem, NOT a solver outcome):
  wrong verifier material / corrupt private bundle
  manifest hash mismatch / unknown generator version

Solver Outcome (candidate quality / execution failure):
  wrong candidate / timeout / parse failure / no candidate
```

An evaluation-level failure aborts the whole run; it is never recorded as a
per-instance solver failure.

### 6.2 Failure report

Each system's report breaks failures down by difficulty:

```text
Model A
D1:
  valid 90%   invalid 5%   timeout 5%
D5:
  valid 40%   invalid 35%  timeout 25%
```

This is often more informative than a single success rate.

## 7. Optimization metrics (OPT)

OPT continues to use `raw_score` / `optimal_score` / `regret`, computed against
the exact bitmask-DP reference:

```text
regret = optimal_score - candidate_score
```

`normalized_regret` is not fabricated unless its definition is meaningful for
the current scoring; nothing is forced into existence.

## 8. Pareto reporting

The report may output **Pareto front data** for Quality-vs-Cost and
Quality-vs-Latency. v0.2 emits the front data; charts are not required.

## 9. Paired comparison

Multiple solvers should run the **same challenge ids**. The report supports a
paired comparison across the shared challenge set:

```text
A wins / B wins / tie / both fail
```

No significance testing is performed in v0.2.

## 10. No leaderboard hallucination

The default report is per-family / per-difficulty / per-metric. It does not
emit "Overall Winner / Best AI / Best Model" unless a caller explicitly
supplies a paired comparison over an identical challenge family, difficulty
distribution, budget, and cost definition.

## 11. Budget protocol

`wall_time_limit`, `token_budget`, and `attempt_budget` may be recorded in a
manifest as `null` (unspecified). Not every solver is required to support them.

## 12. External solver resource measurement

In Command Solver mode the runner at least measures `wall time`, `exit code`,
`stdout size`, and `stderr size`. CPU/memory are only reported if a sandbox can
be safely reused; experimental sandbox capabilities are never presented as a
production claim.

## 13. Research report provenance

Any committed benchmark report / metrics CSV / result summary must record:

```text
generator version / seed / sample count / systems / VICA commit / experiment purpose
```

The report states whether it is `synthetic / test-only` (engineering
validation) or a scientific benchmark. A 5-instance smoke test must never be
written as "Agent A outperforms Agent B on SYNTH".

## 14. SYNTH calibration exit criteria

For SYNTH-v0.1 (the v0.2 flagship), calibration is documented in
`docs/challenge-research/`. The v0.2 exit criteria guides an honest
GO / PIVOT / NO-GO decision:

```text
GO:
  difficulty curve reasonably differentiated
  specialized baselines do not trivially collapse all difficulties
  external agents show meaningful variation
  hidden generalization adds information beyond public fit

PIVOT:
  challenge mostly measures formatting / brute enumeration
  specialized solver trivially dominates
  difficulty presets not monotonic
  public ambiguity overwhelms the intended signal

NO-GO:
  challenge cannot support reliable comparative claims
```

These are not gamed to force a "success" outcome.