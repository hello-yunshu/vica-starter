# VICA Migration Guide

> Location: `docs/MIGRATION.md`
>
> How bundle artifacts produced by earlier VICA versions are read by VICA 1.0.
> The compatibility target is defined in `docs/SPEC.md` §"Compatibility
> Contract"; format details live in `docs/protocol/BUNDLE.md`.

## 1. Compatibility targets

VICA 1.0 can read and reverify artifacts from two bundle format generations:

| Artifact | Format | Generators | 1.0 status |
|----------|--------|-----------|------------|
| Evaluation / Submission / Result Bundle v1 | `bundle_format_version: "1"` | v0.2 generator `0.2.0` (SYNTH), CSP `0.1.0`, OPT | **Stable** — readable and reverifiable |
| Evaluation / Submission / Result Bundle v2 | `bundle_format_version: "2"` | REPO `repo-v0.1` generator `0.3.0` (semantic oracle) | **Stable** — readable and reverifiable |

A bundle is routed strictly by its advertised `bundle_format_version` (the
Bundle dispatcher). A v1 artifact is never silently re-interpreted with v2
semantics, and vice-versa.

## 1.1 v1.0.0 → v1.0.1 (Research Integrity Hotfix)

The transition from 1.0.0 to 1.0.1 changes how REPO results are interpreted and
reverified:

- **REPO generator `0.1.0` is withdrawn for adversarial benchmark use.** Its
  candidate execution shared the verifier interpreter and allowed verifier-frame
  expected-value access — a benchmark research-integrity flaw, *not* a
  hardened-host escape. Under 1.0.1 the generator is `0.2.0`, whose candidate
  verification is **process-separated**: the candidate subprocess receives only
  the case inputs, and the parent evaluator owns the expected values. Historical
  `0.1.0` results are **not** silently re-interpreted under `0.2.0` semantics;
  authoritative reverify of a `0.1.0` result under those semantics is refused.
- **Task Pack v1 → v2.** Dynamic REPO evaluations are now identified as
  `repo-v0.1-generated` (not `repo-v0.1-core`, which is reserved for a truly
  frozen official pack and is not established this round).
- **Strict bundle version pairing.** Evaluation / Submission / Result bundles
  are strictly version-paired (`v1↔v1↔v1`, `v2↔v2↔v2`); cross-version matches
  are refused.
- **Study result persistence.** Per-replicate result bundles now persist under
  `<study-out>/runs/<sid>/r<rep>/` and are never deleted after `run_study`
  returns, with portable relative paths and layered metrics.

## 1.2 v1.0.1 → v1.0.2 (Semantic-Oracle Verifier)

The transition from 1.0.1 to 1.0.2 closes the REPO exact-reference-source lookup
via an independent semantic oracle:

- **REPO generator `0.2.0` is withdrawn for adversarial benchmark use.** Its
  expected values derived from a recoverable fixed source, so an attacker
  enumerating the open-source `Template.builder` could recover the exact
  reference and shortcut the task. Under 1.0.2 the generator is `0.3.0`, whose
  authoritative expected values are computed by a per-template **semantic
  oracle** (an independent, pure `input -> expected` function that is the public
  task specification), never by executing a recoverable `fixed` source.
  Recovering `fixed` now yields no advantage. Historical `0.1.0` / `0.2.0`
  results are **not** silently re-interpreted under `0.3.0` semantics;
  authoritative reverify under those semantics is refused. See
  `docs/challenge-research/repo/semantic-oracle.md`.
- **Task Pack v2 → v3.** The authoritative expected-value derivation changed, so
  0.2.0 packs/results are not silently re-identified under 0.3.0
  (`src/vica/eval/taskpack.py`).

## 2. What can be reverified

1.0 can reverify any artifact whose generator version is still registered in
the shipped verifier. Regenerate the same hidden material, reapply the stored
candidate, re-run the same deterministic verifier, and compare the stored
`valid` / `score` / `error` semantics.

```text
v0.2 CSP/SYNTH/OPT Bundles v1   -> reverifiable
v0.3/v0.4 REPO Bundles v2       -> reverifiable
```

## 3. What can only be inspected

If a future generator is removed or its semantics change, its historical
artifacts remain **loadable for inspection** but are marked
`UNSUPPORTED HISTORICAL GENERATOR` rather than being judged by a new verifier.
VICA 1.0 ships both v1 and v2 readers, so historical CSP/SYNTH/OPT/REPO data
stays inspectable.

## 4. Version axes you must not conflate

- **VICA software version** — `vica.__version__` (currently `1.0.0`).
- **Bundle format version** — `bundle_format_version` (`1` or `2`).
- **Challenge generator version** — per-family `generator_version` (e.g. SYNTH
  `0.2.0`, REPO `0.2.0`).
- **Verifier material version** — commitment scheme version.

Changing any of these independently is supported; a bundle layout change always
bumps `bundle_format_version`.

## 5. Upgrading a project from v0.2

- Existing v1 bundles keep working: `vica eval inspect`, `vica eval verify`,
  `vica reverify` all accept them.
- New REPO work uses v2 bundles produced by `vica eval prepare --challenge
  repo-v0.1 ...`.
- Result Bundles produced by v0.2/v0.3/v0.4 continue to reverify in 1.0 as long
  as the generator and verifier material are unchanged.