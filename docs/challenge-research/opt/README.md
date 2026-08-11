# OPT-v0.1 Research Notes

> Status: **Established (historical)** — OPT is a quality-metric research
> challenge. In v0.2 OPT is not expanded; it only advances regret reporting,
> paired comparison, Pareto reporting, and difficulty curves.

## 1. What OPT measures

OPT-v0.1 is single-machine total-tardiness scheduling `1||ΣT_j` (NP-hard).
Score = `-ΣT_j` (larger is better; 0 = zero tardiness). The exact bitmask-DP
baseline (`opt-dp`, Held-Karp style, O(n·2^n)) is the optimal-score reference.

## 2. Quality metrics

```text
raw_score          candidate's objective score
optimal_score      exact DP reference score
regret             optimal_score - candidate_score   (larger is better = smaller gap)
```

`100% valid` must **not** be interpreted as `100% solved optimally` — every
feasible schedule is "valid", so success rate cannot distinguish quality. The
regret gap is the meaningful signal.

## 3. Difficulty (historical, seed=42, n=200/difficulty)

| d | n | optimal mean score (`-ΣT_j`) | edd vs dp | random vs dp |
|---|----|------------------------------|-----------|--------------|
| 1 | 6 | -0.3 | equal | much worse |
| 2 | 8 | -7.4 | close | worse |
| 3 | 10 | -41.7 | gap | much worse |
| 4 | 12 | -146.3 | gap | worse |
| 5 | 14 | — | — | — |

`opt-brute` is infeasible beyond d3 (12!/14! permutation space), so `opt-dp`
serves as the exact reference. The EDD heuristic (general-purpose, not
optimal) is measurably worse than DP as difficulty grows, giving a regret
gradient that a quality benchmark can use. (Full data:
`docs/reports/opt-v0.1-scale.md`.)

## 4. v0.2 scope

- Add regret reporting to the Result Report (`report.md`).
- Add paired comparison across shared challenge ids.
- Add Pareto reporting (Quality-vs-Cost, Quality-vs-Latency).
- Add difficulty curves.

Not in v0.2: TSP / Packing / Routing / Knapsack / Assignment families.

## 5. Caveat

The difficulty numbers above are from the historical `0.1.0` generator. Under
the current `0.2.0` generator, OPT is not secret-bound (no hidden material), so
the numbers remain comparable, but any new experiment must record its own
provenance.