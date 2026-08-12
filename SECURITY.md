# Security

> Location: `SECURITY.md`
>
> VICA is a **local research arena**. This document describes what VICA's
> security model does and — explicitly — what it does **not** claim. It is
> documentation of the threat model, not a hardened isolation guarantee.

## Verifier correctness model

- Correctness is decided by a **deterministic verifier**, never an LLM judge.
- The verifier is the single authoritative path (`vica eval verify`); solver
  output is untrusted.
- Challenge identity and Result integrity rely on canonical serialization and
  SHA-256 hashes (manifest / challenge / bundle hashes).
- Candidate REPO verification is **process-separated**: the candidate subprocess
  receives only the case inputs, and the parent evaluator owns the expected
  values, so candidate Python frames cannot access evaluator-owned expected
  values. This is a **verifier correctness boundary**, not a hardened OS
  security claim.

## Secret isolation for coding agents

- Reference targets and hidden tests are **secret-bound** (HMAC-SHA256,
  domain-separated) so the public `(seed, difficulty)` alone cannot recover
  them.
- A coding agent is given only the **public** Evaluation Bundle, never the
  private verifier material or the evaluator secret.
- The agent's execution environment defaults to a safe allowlist. A solver's
  own API keys are forwarded only via explicit `--pass-env`; **verifier-reserved**
  secrets (`VICA_VERIFIER_SECRET`, `VICA_PRIVATE_*`) are never forwarded, even
  if requested.
- Execution profiles record forwarded environment **names** and never secret
  **values**.

## Sandbox limits (explicitly not hardened)

- The OS sandbox (`src/vica/sandbox/`) is an **experimental local process
  isolation prototype**, not a hostile-code isolation boundary.
- Memory limits are Linux-only; network namespace / chroot are Linux+root and
  off by default.
- The sandbox does **not** provide hardened filesystem/network isolation.
  Do not run untrusted arbitrary code against a real host with it.

## Supporting / disclosure

- Report suspected security issues privately to the maintainers rather than
  opening a public issue. Do not include verifier secrets, hidden tests, or
  private benchmark material in a report.
- VICA does not claim to be an unhackable benchmark or a hardened arbitrary-code
  sandbox. Its value is deterministic, reproducible, and independently
  reverifiable evaluation under an explicit threat model
  (`docs/challenge-research/repo/threat-model.md`).