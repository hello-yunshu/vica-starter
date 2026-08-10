# AGENTS.md

This repository contains VICA — Verifiable Intelligence Compute Arena.

## Required reading

Before changing protocol, challenge, verifier, benchmark, or metrics code, read:

- `docs/VISION.md`
- `docs/SPEC.md`
- `docs/ROADMAP.md`
- `docs/TASKS.md`

## Project invariants

1. Core verification is deterministic.
2. Correctness never depends on an LLM judge.
3. Challenge generation is reproducible from version + seed + difficulty.
4. Solver output is untrusted.
5. Every challenge has a traditional/non-AI baseline.
6. Benchmark code does not favor a particular provider or model.
7. A specialized solver outperforming AI is a valid research result.
8. Do not add blockchain, token, wallet, mining, staking, consensus, or P2P functionality unless explicitly requested by the maintainer.
9. Protocol changes require tests.
10. Keep public schemas stable; version breaking changes.

## Engineering defaults

- Python 3.12+
- Pydantic v2
- pytest
- Ruff
- src/ layout
- SQLite for MVP
- type hints on public APIs
- network calls isolated in provider adapters
- API credentials only via environment variables
