# VICA Coding Agent Prompt Pack

这些提示词用于 Codex、Claude Code、ChatGPT coding agent 或类似工具。

原则：

- 一次只给 Agent 一个明确阶段
- 要求先读仓库文档
- 不允许 Agent 擅自扩大 scope
- 所有核心协议改动必须补测试
- Challenge 与 Verifier 必须 deterministic
- 不允许以 LLM Judge 替代 verifier

---

# Prompt 0 — Project Bootstrap

```text
You are the lead engineer bootstrapping the VICA repository.

VICA stands for Verifiable Intelligence Compute Arena. It is a benchmark and research platform where AI models, agents, traditional solvers, and hybrid systems solve automatically generated tasks that have deterministic, cheap verification.

Before changing anything, read:
- README.md
- docs/VISION.md
- docs/SPEC.md
- docs/ROADMAP.md
- docs/TASKS.md

Current goal:
Implement only Milestone M0: repository bootstrap.

Requirements:
1. Use Python 3.12+.
2. Use src/ layout.
3. Configure pytest.
4. Configure Ruff.
5. Add mypy with pragmatic initial settings.
6. Add a minimal CLI entry point named `vica`.
7. Add GitHub Actions CI that runs tests and lint.
8. Do not implement Challenge logic yet.
9. Keep dependencies minimal.
10. Update README only when required for exact setup commands.

Deliver:
- files changed
- commands to run locally
- tests added
- any design decisions that may affect later protocol work

Do not invent blockchain, token, mining, wallet, consensus, or distributed-network features.
```

---

# Prompt 1 — Protocol Core

```text
Act as a protocol engineer for VICA.

Read:
- docs/VISION.md
- docs/SPEC.md
- docs/TASKS.md

Implement Milestone M1 only.

Create the core protocol models and deterministic serialization utilities.

Required objects:
- Challenge
- CandidateSubmission
- VerificationResult
- SolveOutput
- RunRecord

Required utilities:
- canonical_json_bytes(obj)
- stable_hash(obj)

Requirements:
- Pydantic v2 for external protocol models.
- canonical serialization must be deterministic.
- UTF-8.
- sorted JSON object keys.
- no NaN/Infinity.
- no irrelevant whitespace.
- stable unit tests with golden vectors.
- include Unicode cases.
- hash function can use SHA-256 in v0.1.
- protocol code must not access network or system time.
- add type hints.
- add tests for malformed objects.

Do not implement CSP yet.

Before finishing:
1. run tests;
2. run lint;
3. summarize API surfaces created;
4. flag any cross-language serialization concern.
```

---

# Prompt 2 — CSP-v0.1 Generator

```text
You are implementing the first VICA Challenge Family: CSP-v0.1.

Read the entire docs/SPEC.md section on CSP-v0.1 before editing code.

Goal:
Implement a deterministic constraint-satisfaction challenge generator.

Critical design rule:
Generate a hidden valid assignment first, then derive constraints from that assignment. Do not randomly produce unconstrained formulas and hope they are satisfiable.

Inputs:
- seed: string
- difficulty: integer

Outputs:
A Challenge payload containing:
- variables
- domains
- constraints
- no hidden solution

Supported constraint types for v0.1:
- eq
- neq
- lt
- add_eq
- xor_eq
- modular_sum_eq
- all_different

Requirements:
- same seed + same difficulty => byte-identical canonical payload;
- all generated instances must have at least one valid solution;
- use a local deterministic PRNG seeded only from protocol inputs;
- do not use system time;
- do not access the network;
- implement difficulty presets rather than pretending the scale is already scientifically calibrated;
- provide comprehensive unit tests.

Also implement an internal test-only helper that can expose the hidden generated solution so tests can prove generated challenges are satisfiable. This helper must not leak the hidden solution into public Challenge payloads.
```

---

# Prompt 3 — CSP Deterministic Verifier

```text
Implement the CSP-v0.1 verifier for VICA.

Read:
- docs/SPEC.md
- existing CSP generator implementation
- protocol models

Security and correctness requirements:
- treat candidate input as untrusted;
- malformed candidates must return a clean invalid result, never crash the benchmark runner;
- require every expected variable exactly once;
- reject unexpected variables in v0.1;
- reject booleans masquerading as integers;
- enforce domain bounds;
- evaluate every constraint deterministically;
- verifier must not call any external service;
- verifier must not use an LLM;
- verifier must not mutate challenge or candidate;
- verifier result must be reproducible.

Add tests for:
- valid hidden solution
- missing variable
- extra variable
- wrong type
- out-of-range value
- each constraint type failing individually
- malformed payload
- repeated verification producing identical results

Measure verification time outside the logical verifier if practical; correctness should not depend on timing.
```

---

# Prompt 4 — Baseline Solvers

```text
Implement two VICA CSP-v0.1 baseline systems:

1. RandomAssignmentSystem
2. Z3SolverSystem

Read docs/SPEC.md and docs/TASKS.md first.

Both systems must implement the same SolverSystem interface.

RandomAssignmentSystem:
- supports max_attempts
- supports a time budget
- uses a deterministic seed when benchmark runner provides one
- returns useful metadata

Z3SolverSystem:
- converts VICA CSP constraints to Z3
- supports timeout
- extracts a candidate
- never bypasses the official VICA verifier
- reports solver latency and status metadata

Important:
The purpose of Z3 is partly adversarial: if Z3 dominates this Challenge family, the benchmark should make that visible.

Add tests for both systems.
Do not modify the Challenge to make an AI system look better.
```

---

# Prompt 5 — Benchmark Runner

```text
Implement the VICA benchmark runner.

Goal:
Run one or more SolverSystem implementations over a reproducible batch of Challenge instances and persist per-run results.

Read:
- docs/SPEC.md
- docs/TASKS.md

Runner responsibilities:
1. generate challenge batch;
2. derive deterministic per-run seeds;
3. call solver;
4. isolate solver exceptions;
5. measure wall-clock solve latency;
6. call official verifier;
7. measure verification latency;
8. record candidate and metadata;
9. persist results;
10. aggregate metrics.

Required aggregate metrics:
- challenge count
- success rate
- valid count
- mean latency
- p50 latency
- p95 latency
- mean cost per challenge when available
- cost per valid solution when available
- valid solutions per dollar when meaningful

CLI target:

vica benchmark \
  --challenge csp-v0.1 \
  --difficulty 3 \
  --systems random,z3 \
  --instances 1000 \
  --seed 42

Requirements:
- no hidden retries unless the chosen solver strategy explicitly owns them;
- one failed solver call must not terminate the full experiment;
- preserve raw run records;
- tests must include deterministic small benchmark runs.
```

---

# Prompt 6 — First LLM Adapter

```text
Implement the first generic LLM-based SolverSystem adapter for VICA.

Do not hard-code protocol logic into the model adapter.

Architecture:
Challenge
  -> prompt renderer
  -> model client
  -> raw model output
  -> strict candidate parser
  -> CandidateSubmission
  -> official VICA verifier

Requirements:
- provider-specific client code must be isolated behind an adapter;
- model output must be parsed as strict JSON;
- do not repair invalid answers using hidden verifier knowledge;
- retry behavior must be explicit and counted;
- capture input/output token counts when provider exposes them;
- capture wall time;
- capture estimated cost only from a configurable pricing table, never silently hard-code prices as permanent truth;
- API keys only from environment variables;
- never log API keys;
- include a mock client so tests do not make network requests.

Prompt goal for CSP:
Return only a JSON object mapping every variable name to one integer.

Do not change CSP generator or verifier to accommodate the model.
```

---

# Prompt 7 — Experiment Review

```text
Act as a skeptical research engineer reviewing VICA's first CSP benchmark results.

Do not optimize for flattering AI systems.

Given the exported benchmark data, answer:

1. Does CSP-v0.1 meaningfully distinguish systems?
2. Is solve cost materially larger than verify cost?
3. How does success rate change with difficulty?
4. Does Z3 or another specialized solver trivialize the benchmark?
5. Are model results stable across seeds?
6. Is cost-per-valid-solution a meaningful metric here?
7. Are there signs of benchmark gaming or parser artifacts?
8. Which claims are supported by data?
9. Which claims are not supported?
10. Should CSP-v0.1 be kept as:
   - infrastructure test only,
   - benchmark family,
   - or retired?

Produce:
- concise executive conclusion;
- evidence table;
- failure modes;
- recommended next experiment.

Do not introduce blockchain/token/mining narratives.
```

---

# Prompt 8 — SYNTH-v0.1 Design Only

```text
You are a security-conscious benchmark designer.

Design VICA Program Synthesis Challenge Family SYNTH-v0.1.

Do NOT implement code yet.

The task family must target:
Hard to Solve, Easy to Verify.

Define:
- challenge generation method;
- how tasks avoid simply reproducing common textbook functions;
- public examples;
- hidden tests;
- candidate language;
- code size limit;
- runtime limit;
- memory limit;
- deterministic scoring;
- difficulty controls;
- reproducibility;
- baseline algorithms;
- likely shortcuts;
- data leakage risks;
- model memorization risks;
- sandbox requirements;
- expected solve/verify cost ratio.

Critical:
Do not use an LLM judge.
The verifier must be deterministic.

Also write an attack plan:
How would a specialized non-LLM solver try to dominate this benchmark?

End with a GO / REVISE / REJECT recommendation for the proposed design.
```

---

# Prompt 9 — Sandbox Security Review

```text
Act as an application security engineer reviewing VICA's planned program-synthesis sandbox.

Assume all candidate programs are hostile.

Threat model includes:
- arbitrary code execution
- filesystem reads/writes
- environment secret theft
- network exfiltration
- fork bombs
- memory exhaustion
- CPU exhaustion
- oversized stdout/stderr
- subprocess abuse
- syscall abuse
- container escape attempts
- timing attacks where relevant

Review the proposed sandbox architecture and identify:
- isolation boundary;
- trust assumptions;
- unsafe host integrations;
- resource limits;
- cleanup guarantees;
- logging risks;
- secret exposure;
- recommended malicious test corpus.

Do not accept Python `exec`, subprocess-only isolation, or application-level timeouts as sufficient sandboxing.

Return findings ordered by severity and provide a minimum safe architecture for a public Arena.
```

---

# Prompt 10 — New Challenge Design

```text
Design a new VICA Challenge Family.

The task must aim to satisfy:

1. Hard to solve.
2. Cheap deterministic verification.
3. Automatically generatable instances.
4. Difficulty can be adjusted.
5. Low value of precomputation.
6. Objective correctness or objective score.
7. Multiple possible solution strategies.
8. It must not require an LLM judge.

For the proposed challenge, provide:
- exact input schema;
- exact candidate schema;
- deterministic verifier;
- scoring function;
- difficulty parameters;
- naive baseline;
- strongest obvious specialized algorithm;
- expected AI advantage, if any;
- likely benchmark shortcut;
- memorization/data leakage risk;
- solve/verify complexity;
- falsification experiment.

Important:
Assume the benchmark is wrong until experiments show otherwise.
The goal is not to create a task that makes LLMs win; the goal is to discover whether general-purpose intelligent systems have measurable efficiency advantages.
```

---

# Prompt 11 — Repository-Wide Agent Rules

可放到 coding agent 的 system/project instructions：

```text
You are working in the VICA repository.

Non-negotiable rules:

1. Read docs/VISION.md and docs/SPEC.md before protocol changes.
2. Never add blockchain, token, wallet, mining, consensus, or P2P features unless the roadmap is explicitly changed by the human maintainer.
3. Core verification must be deterministic.
4. Never use an LLM judge for correctness.
5. Never modify a verifier to favor a particular model.
6. Every Challenge generator must be reproducible from version + seed + difficulty.
7. Treat all solver output as untrusted.
8. Every protocol change requires tests.
9. Every new Challenge requires at least one non-AI baseline.
10. Prefer falsifiable experiments over architectural speculation.
11. Keep dependencies minimal.
12. Do not silently change public schemas.
13. Record important design tradeoffs in docs.
14. A specialized traditional solver beating AI is a valid result, not a bug.
15. Optimize for research integrity, reproducibility, and security.
```
