# REPO-v0.1 Threat Model

> Status: **Established** — the model below is explicit and the 
> shortcut-audit probes (§47) are implemented and tested. The OS sandbox is
> **experimental local process isolation, NOT hardened hostile-code isolation**
> (§32). No claim is made of full security isolation against a hostile
> arbitrary-code attacker.

## 1. Participant model

VICA's verifier is authoritative and deterministic; it does not rely on an LLM
judge. The threat model distinguishes four actor classes to keep claims honest:

| actor | description | isolation expectation |
|-------|-------------|----------------------|
| **honest benchmark participant** | submits a genuine patch | verifier returns correct pass/fail |
| **curious agent** | may probe env / look for hidden material that is present but not intended | hidden material is not present in the public workspace; env does not leak secrets |
| **adversarial agent** | actively tries shortcut cheats (delete tests, hard-code, symlink, path traversal, oversized/malformed patch) | shortcuts are enumerated and rejected as solver outcomes, not successes |
| **hostile arbitrary-code attacker** | runs arbitrary code on the host and tries to break out of the sandbox | **not claimed** — OS sandbox is experimental, not hardened isolation |

## 2. What the verifier guarantees

- **Never runs on the original workspace.** The workspace is materialized into
  a fresh temp dir and discarded (§23).
- **Structural violations rejected before execution.** Modifying protected
  paths (`tests/`, `private/`), touching too many files, or an oversized /
  malformed patch is a `STRUCTURAL_VIOLATION` / `PATCH_APPLY_FAILURE` before any
  patched code runs (§30).
- **No hidden leaks.** Active hidden test data and reference patches are never
  placed in the solver-visible workspace (§20); they are secret-derived.
- **Verifier secret never reaches the agent.** `VICA_VERIFIER_SECRET` and
  `VICA_PRIVATE_*` are never forwarded to the agent, even if requested
  (§37/§68). Only explicitly `--pass-env` names are forwarded.

## 3. What is NOT claimed

- **Not** hardened hostile-code isolation. Filesystem / network isolation is
  incomplete (§32).
- **Not** a guarantee against a determined attacker running truly arbitrary
  code on the host.
- **Not** a universal-coding-agent difficulty scale (§45). Difficulty is a
  preset / experimental calibration.

## 4. Result integrity

The Result Bundle records non-secret REPO facts (`workspace_hash`, `patch_hash`,
`patch_bytes`, `changed_files`, `changed_lines`, `task_kind`) and never the
hidden tests, the reference patch, or the verifier secret (§48). Strict reverify
recomputes the authoritative REPO facts and binds `workspace_hash` + `patch_hash`
so a tampered stored result is detected even when valid/score/status coincide
(§50).