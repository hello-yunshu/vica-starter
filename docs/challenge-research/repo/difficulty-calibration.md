# REPO-v0.1 Difficulty Calibration

> Status: **Structural calibration established; agent-performance calibration
> pending.** Difficulty presets are validated structurally (files, hidden case
> count, task semantics). No empirical monotonic *agent* difficulty is claimed
> because no real coding agent was measured (§79 / §81).

## 1. Difficulty presets

Each difficulty is a `Preset` (`src/vica/repo/generator.py`):

| difficulty | public cases | hidden cases |
|-----------|--------------|--------------|
| 1 | 4 | 6 |
| 2 | 4 | 10 |
| 3 | 4 | 14 |

Difficulty is scoped to 1–3 in v0.3 (§45). It is a **preset / experimental
calibration**, not a universal intelligence scale.

## 2. What difficulty controls

Higher difficulty raises the number of hidden test cases (the discriminating
negative control) and thereby the confirmation load on a candidate patch. The
task templates may also use difficulty to vary the amount of incomplete
implementation / interaction depth internally, but the generator's released
preset contract is the public/hidden case counts above.

## 3. Structural calibration (established)

The survey (40 seeds × difficulties 1–3) confirms:

```text
reference pass   100% at every difficulty
NoOp hidden-fail 100% at every difficulty
hidden case count d1=6 < d2=10 < d3=14  (strictly increasing)
```

Hidden test count strictly increases with difficulty, so the verification
burden (and therefore the surface for hidden-only failures) grows with
difficulty. This is a **structural** calibration.

## 4. Agent-performance calibration (pending)

No real coding agent (codex / claude / aider / etc.) was available and
authenticated to run, so no agent success-rate curve is reported (§81):

```text
external-agent empirical calibration: Not Yet Established
```

This is recorded honestly; it does not block v0.3 release because protocol,
verifier, task validity, reference/noop controls, and shortcut audit are all
complete (§81).

## 5. Caveat

Do not interpret the structural monotonic hidden-case count as an empirical
monotonic *agent* difficulty. That claim requires measured agent data and is
explicitly left pending.