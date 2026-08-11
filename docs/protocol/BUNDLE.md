# VICA Bundle Formats (v0.2)

> Location: `docs/protocol/BUNDLE.md`
>
> This document defines the three portable artifacts of the Benchmark
> Research & External Evaluation milestone and how they flow into each other.
> The statistical / reporting method lives in
> `docs/BENCHMARK_METHODOLOGY.md`; the protocol-layer changes are summarized in
> `docs/SPEC.md` §17.

The three bundles form a strict pipeline:

```text
Evaluation Bundle
        ↓  (public part handed to a solver)
Submission Bundle
        ↓  (authoritative verification)
Result Bundle
```

These are **portable file artifacts**, intentionally decoupled from the local
SQLite experiment history. A benchmark need not touch the database to be
produced, shared, or independently reverified.

---

## 1. Version concepts

VICA distinguishes five version axes that must never be conflated:

| Axis | Meaning | Example carrier |
|------|---------|-----------------|
| VICA software version | version of the VICA package | `vica.__version__` |
| Protocol version | semantics of `vica.protocol` | protocol modules |
| Challenge generator version | semantics of a challenge family generator | `family.generator_version` |
| **Bundle format version** | format of the bundle files | `bundle_format_version` |
| Verifier material version | commitment scheme / hidden-material derivation | `verifier/material.py MATERIAL_VERSION` |

Changing a bundle's layout always bumps `bundle_format_version`. This is
independent of the VICA software version and of each challenge generator
version.

---

## 2. Evaluation Bundle

An Evaluation Bundle separates **public** solver material from **private**
verifier material so an external solver / coding agent can be handed only the
public part.

```text
<evaluation>/
├── public/
│   ├── manifest.json         # solver-visible metadata + challenges_hash
│   ├── challenges.jsonl      # solver-visible Challenge (one per line)
│   └── README.md
└── private/
    ├── manifest.json         # verifier-material references + public hash link
    └── verifier-material.json  # evaluator secret (0600)
```

### 2.1 Public manifest

Contains only solver-visible fields:

```json
{
  "bundle_format_version": "1",
  "evaluation_id": "eval-<sha256[:12]>",
  "vica_version": "0.1.0",
  "challenge_type": "synth-v0.1",
  "generator_version": "0.2.0",
  "seed": 42,
  "difficulties": [1, 2, 3],
  "instances_per_difficulty": 20,
  "challenge_count": 60,
  "verifier_material_commitment": "<sha256 hex or null>",
  "verifier_material_version": "1",
  "challenges_hash": "<sha256 hex>",
  "manifest_hash": "<sha256 hex>"
}
```

### 2.2 Private part

The private manifest references the public manifest hash and the material
commitment. The `verifier-material.json` holds the verifier secret (permission
`0600`). For non-secret-bound families (CSP / OPT) no secret is stored and the
commitment is `null`.

### 2.3 Identity & integrity

```text
manifest_hash    = SHA-256(canonical(manifest without "manifest_hash"))
challenges_hash  = SHA-256(canonical(challenge_list))
evaluation_id    = "eval-" + SHA-256(canonical(definition inputs))[:12]
```

- Hashing uses `vica.protocol.serialization` (sorted keys, no extra space,
  stable numbers) — never a raw `json.dumps`.
- A manifest never hashes itself; the `manifest_hash` field is removed before
  hashing.
- Any rewrite of a challenge line is detected by `challenges_hash` on
  `inspect` / `verify`.

### 2.4 Security boundary

`public/` and `private/` sharing a parent directory is **evaluator bundle
organization, not OS security isolation**. A Coding Agent must be given only
`public/`, never the whole evaluation directory. The public part contains no
verifier secret, no hidden tests, and no reference target.

---

## 3. External Solver Protocol

Two minimal modes; correctness depends only on the authoritative verifier.

### 3.1 Mode A — File Exchange (first priority)

The solver reads `public/challenges.jsonl` and writes a `submissions.jsonl`.
Any agent, human, or script can participate without calling the VICA Python
API. This is the recommended workflow for Coding Agents.

### 3.2 Mode B — Command Solver (second priority)

```bash
vica solver run \
  --command "python solver.py" \
  --bundle <evaluation/public> \
  --out <submission> \
  --system my-command-solver
```

VICA runs the command once per challenge, writing the challenge as a single
JSON object to the process stdin and reading the candidate as a single JSON
object from stdout. The runner records wall time, exit code, and stdout/stderr
byte counts. A nonzero exit, malformed output, or timeout marks that instance
as failed without aborting the whole run.

### 3.3 Solver output format

```json
{
  "challenge_id": "...",
  "candidate": {},
  "metadata": {
    "solver": "...",
    "model": "...",
    "attempts": 1
  }
}
```

`metadata` is untrusted self-report. Correctness comes only from the verifier.

---

## 4. Submission Bundle

The untrusted output of an external solver:

```text
<submission>/
├── manifest.json
└── submissions.jsonl
```

The manifest records `submission_bundle_version`, `evaluation_id`,
`system_id`, `system_metadata`, and `created_at`. It is not required to be
trustworthy.

### 4.1 Validation semantics

| Input condition | Behavior |
|-----------------|----------|
| unknown challenge id | reject the bundle (structured error) |
| duplicate challenge id | reject the ambiguous input (never silently keep the last) |
| missing challenge | recorded per-instance as `NO_SUBMISSION` (not `INVALID_SOLUTION`) |
| malformed candidate | recorded as a per-instance `PARSE_ERROR`, not a whole-bundle rejection |

A single malformed candidate does not discard the batch (candidate error
isolation). The Submission Bundle is untrusted input, so sensible limits are
imposed on line bytes and submission count to avoid trivial memory exhaustion.

---

## 5. Authoritative Verification

`vica eval verify` is the single authoritative path. It reuses
`verify_submission()` — there is **no second verifier**.

```text
load public manifest            ->  load private verifier material
        -> validate bundle hashes
        -> match submission challenge_id
        -> reconstruct Challenge
        -> validate material commitment
        -> verify_submission()
        -> record raw result
        -> metrics
        -> result bundle
```

A wrong private bundle (evaluation A public paired with evaluation B private)
is detected before any solver is judged and raises an **Evaluation Failure**,
never a per-instance solver failure.

---

## 6. Result Bundle

A portable, reverifiable research artifact:

```text
<result>/
├── manifest.json
├── evaluation.json
├── system.json
├── environment.json
├── challenges.jsonl
├── submissions.jsonl
├── results.jsonl
├── metrics.json
└── report.md
```

### 6.1 Manifest integrity

The manifest carries per-file `sha256:<hex>` hashes under `files` plus a
`bundle_hash` (SHA-256 of the manifest without its own `bundle_hash`). Loading
verifies both, so any modification is detected. No digital signature is used
in v0.2; content integrity is sufficient.

### 6.2 What a Result Bundle records

```text
bundle_format_version   evaluation manifest hash   VICA version
git commit              challenge generator version
verifier material commitment   system id / provenance
raw submissions         raw verification results  metrics
environment metadata
```

### 6.3 What a Result Bundle must NOT contain

```text
verifier secret
private reference target
hidden tests
API keys / credentials
```

A post-benchmark reveal bundle is out of scope for v0.2.

---

## 7. Reverify (strict)

`vica reverify <result-bundle> --evaluation <evaluation>` does **not**
re-invoke a solver. It reloads the stored candidates and challenges, reloads
the evaluator verifier material, and runs the same `verify_submission()` again,
then recomputes metrics.

Strict mode (the only mode in v0.2) requires:

```text
same generator version
same material commitment
same challenge id
same verifier semantics
```

otherwise it refuses. `valid` / `score` / `error_code` must match the stored
results; `solve_wall_time_ms` / `verify_time_us` are telemetry and may differ.

---

## 8. Path & input safety

When reading bundles, relative file references are resolved and kept under the
bundle root (`..`, absolute paths, and symlink escapes are rejected). Manifest,
jsonl, and candidate inputs have size limits. This is lightweight defense, not
an OS sandbox.

---

## 9. End-to-end flow (v0.2 acceptance criterion)

```text
vica eval prepare ...          -> public challenge bundle
      ↓ (handed to any Coding Agent / LLM / traditional solver / human / script)
submission bundle
      ↓
vica eval verify ...           -> result bundle
      ↓ (any researcher holding the correct evaluator material)
vica reverify ...              -> identical valid / score / error semantics
```

This is the true test of whether v0.2 is complete.