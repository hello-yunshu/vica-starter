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
| Evaluation / Submission / Result Bundle v2 | `bundle_format_version: "2"` | REPO `repo-v0.1` generator `0.1.0` | **Stable** — readable and reverifiable |

A bundle is routed strictly by its advertised `bundle_format_version` (the
Bundle dispatcher). A v1 artifact is never silently re-interpreted with v2
semantics, and vice-versa.

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
  `0.2.0`, REPO `0.1.0`).
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