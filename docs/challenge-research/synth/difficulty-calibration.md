# SYNTH-v0.1 Difficulty Calibration

> Status: **Established (historical)** — d4/d5 calibration was validated on the
> historical `0.1.0` generator. Re-calibration under the current secret-bound
> `0.2.0` generator is `Not Yet Established`.

## 1. Preset structure

Each difficulty is a `Preset` (`src/vica/challenges/synth_v01/family.py`):

| d | ops | unary | max_depth | input_width | params | min_nodes | reject_constant |
|---|-----|-------|-----------|-------------|--------|-----------|-----------------|
| 1 | `+ -` | — | 2 | 20 | x | 0 | no |
| 2 | `+ - * %` | — | 3 | 20 | x | 0 | no |
| 3 | `+ - * % // min max` | — | 4 | 20 | x,y | 0 | no |
| 4 | full | `abs` | 5 | 20 | x,y | 5 | yes |
| 5 | full | `abs neg` | 6 | 20 | x,y,z | 7 | yes |

## 2. The problem that motivated calibration

A 200-instance run on the historical generator showed a non-monotonic curve: the
brute-force success rate **rebounded** at d4 (54%) instead of decreasing. Root
cause: adding `abs` / `neg` to the operator pool inflated the share of small /
effectively-constant targets, which are easier for enumeration / random to hit.

## 3. Calibration method

`scripts/calibrate_synth.py` reproduces the target-generation loop under a
custom `Preset`, runs the brute-force baseline, and reports:

```text
success_rate   brute-force success through hidden tests
solved_rate    brute found any public-passing candidate
constant_rate  share of effectively-constant sampled targets
node counts    mean / max target complexity
brute_ms       mean solve wall time
```

Two filters were evaluated:

```text
reject_constant True   drop targets constant over 20 random inputs
min_nodes       N      drop targets with fewer than N AST nodes
```

## 4. Result (historical generator, seed=42, n=200/difficulty)

| d | brute (before → after) | random (before → after) |
|---|------------------------|-------------------------|
| 3 | 47.5% → 47.5% | 16% → 16% |
| 4 | 54.0% → **23.0%** | 24% → **7.5%** |
| 5 | 47.5% → **11.0%** | 19% → **2.0%** |

Calibrated brute curve: **100% → 65.5% → 47.5% → 23% → 11%** (strictly
monotonic). Random is also monotonic.

## 5. Interpretation

- The d4/d5 calibration restores strict monotonic difficulty.
- The large drop in random (2% at d5) indicates the search space is genuinely
  hostile to random hit at high difficulty — a promising signal for measuring
  general-purpose reasoning, **provided** hidden generalization adds information
  beyond public fit (see `generalization.md`).

## 6. Caveat / next step

These numbers come from the historical `0.1.0` generator (target derived from
the public seed). The current `0.2.0` generator is secret-bound; the curve must
be re-measured under it before the difficulty claim is re-asserted.

> Status of current-generator curve: `Not Yet Established`.