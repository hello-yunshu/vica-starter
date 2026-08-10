# VICA Implementation Tasks

下面按实际编码顺序拆分。

---

## Milestone M0 — Repository Bootstrap

- [x] 初始化 Git 仓库
- [x] 配置 `pyproject.toml`
- [x] 配置 `src/` layout
- [x] 加入 pytest
- [x] 加入 Ruff
- [x] 加入 mypy（可先宽松）
- [x] 建立 CI
- [x] README 指向各设计文档

完成标准：

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

全部通过。

---

## Milestone M1 — Protocol Core

### Models

- [x] `Challenge`
- [x] `CandidateSubmission`
- [x] `VerificationResult`
- [x] `SolveOutput`
- [x] `RunRecord`

建议 Pydantic v2。

### Serialization

- [x] `canonical_json_bytes(obj)`
- [x] `stable_hash(obj)`
- [x] golden test vectors
- [x] Unicode tests
- [x] invalid float tests

### Interfaces

- [x] `ChallengeFamily`
- [x] `SolverSystem`
- [x] `Verifier`

---

## Milestone M2 — CSP-v0.1

### Generator

- [x] deterministic PRNG
- [x] hidden solution generation
- [x] variable generation
- [x] constraint generation
- [x] difficulty presets
- [x] seed reproducibility tests

### Verifier

- [x] candidate schema check
- [x] missing variable handling
- [x] extra variable handling
- [x] integer range check
- [x] all constraint operators
- [x] malformed input never crashes verifier

### Tests

- [x] known valid candidates
- [x] known invalid candidates
- [x] random fuzz-ish invalid candidates
- [x] deterministic generation test

---

## Milestone M3 — Baselines

### Random Baseline

- [x] random assignment generator
- [x] fixed attempt budget
- [x] timeout support
- [x] metadata collection

### Traditional Solver

建议第一版用 Z3。

- [x] CSP -> Z3 conversion
- [x] solve
- [x] timeout
- [x] metadata
- [x] verify returned candidate through VICA verifier

原则：

即使 solver 自己声称 SAT，也必须经过统一 verifier。

---

## Milestone M4 — Arena Runner

- [x] generate batch
- [x] run system against batch
- [x] measure wall time
- [x] call verifier
- [x] record result
- [x] graceful timeout handling
- [x] exception isolation
- [x] deterministic experiment seed

CLI 草案：

```bash
vica benchmark \
  --challenge csp-v0.1 \
  --difficulty 3 \
  --systems random,z3 \
  --instances 1000 \
  --seed 42
```

---

## Milestone M5 — Storage & Reporting

- [x] SQLite schema
- [x] result repository
- [x] CSV export
- [x] JSON export
- [x] aggregate metrics
- [x] p50 / p95 latency
- [x] success rate
- [x] cost per valid solution

CLI：

```bash
vica report <experiment-id>
```

---

## Milestone M6 — First Model Adapter

先只接一个模型，验证 abstraction。

- [x] adapter config
- [x] prompt template
- [x] JSON-only candidate parsing
- [x] timeout
- [x] retry
- [x] token usage
- [x] cost field
- [x] invalid JSON handling

重要：

模型 Adapter 不允许修改 verifier。

---

## Milestone M7 — 1,000 Instance Experiment

至少测试：

- Random
- Z3
- Model A

Difficulty：

- 1
- 2
- 3
- 4
- 5

输出：

- success rate
- solve latency
- verify latency
- cost
- attempts
- difficulty curve

写：

```text
docs/reports/csp-v0.1-first-run.md
```

---

## Milestone M8 — SYNTH-v0.1 Design

编码前先完成设计审查。

- [x] 设计评审完成：`docs/reports/synth-v0.1-design.md`（等待确认开放问题后再实现）

必须明确：

- 任务如何自动生成
- 如何避免训练集记忆
- public / hidden tests
- candidate language
- sandbox
- runtime budget
- memory budget
- code size limit
- deterministic verifier
- baseline attacks

只有设计审查通过后再实现。

---

## Milestone M9 — Sandbox

Program Synthesis 的最高安全优先级任务。

要求：

- [x] network disabled
- [x] read-only minimal filesystem
- [x] CPU time limit
- [x] wall time limit
- [x] memory limit
- [x] process limit
- [x] output limit
- [x] syscall restriction / container isolation
- [x] cleanup after execution
- [x] malicious candidate tests

实现：`src/vica/sandbox/`（`run_sandboxed` + `SandboxLimits`），
`tests/test_sandbox.py`。

跨平台说明（macOS 开发机 + Linux CI）：

- CPU / wall / output / fd / core / process 限制在所有平台生效。
- 内存限制（RLIMIT_AS/DATA）仅 Linux 生效：macOS 上 fork 子进程继承约
  400GiB 虚拟数据足迹，有限 AS/DATA 会让 exec 在候选运行前中止；macOS 内存
  隔离交由未来的容器 / sandbox-exec 后端。
- 网络禁用（unshare CLONE_NEWNET）与 read-only chroot 仅 Linux + root 生效；
  非 root / macOS 时跳过并告警，rlimit + 进程组 + 输出上限保证始终生效。
- 墙钟超时后 killpg(SIGKILL) 清理整个进程组（含 fork 出的孙进程）。

禁止：

```python
exec(candidate)
```

直接运行于 Arena 主进程。

> **注**：SYNTH-v0.1 使用纯 DSL 解释器（无 `exec`、无网络、无文件系统访问），
> 解释器级沙箱守卫已在 M10 中实现并通过测试。M9 的 OS 级沙箱要求面向未来
> 支持任意语言代码执行的 Challenge Family。

---

## Milestone M10 — SYNTH-v0.1 Implementation

### Generator

- [x] deterministic PRNG (seed + difficulty)
- [x] difficulty presets (d1-d5: ops/depth/vars 三维可调)
- [x] trivial target filtering (拒绝纯 var/num 目标)
- [x] public / hidden test generation (10 public + 40 hidden)
- [x] seed reproducibility tests

### DSL (Candidate Language)

- [x] lexer / recursive-descent parser
- [x] canonical infix printer (round-trip verified)
- [x] iterative post-order evaluator (无栈溢出)
- [x] operators: `+ - * % // min max abs neg`

### Sandbox Guards (interpreter-level)

- [x] program length cap (1 MiB)
- [x] token count cap (4096)
- [x] parse nesting depth cap (96)
- [x] eager evaluation step cap (200k)
- [x] per-op integer bit-length cap (65536 bits)
- [x] adversarial wide-expression tests (栈溢出 → SandboxLimit)

### Verifier

- [x] deterministic hidden test regeneration (from seed + difficulty)
- [x] candidate schema check
- [x] parse / eval error mapping to ErrorCode
- [x] sandbox limit mapping to ErrorCode.SANDBOX_ERROR
- [x] malformed input never crashes verifier

### Registry & Runner Integration

- [x] SYNTH-v0.1 registered in `challenges/registry.py`
- [x] `verify_candidate` passes full challenge dict
- [x] `verify_submission` compatible with CSP and SYNTH
- [x] CLI `challenges` command lists SYNTH-v0.1 presets

### Baselines

- [x] `synth-random`: random AST generation baseline
- [x] `synth-brute`: enumerative brute-force baseline (traditional solver)
- [x] both registered in `arena/runner.py` SYSTEM_FACTORIES
- [x] both pass through unified verifier

### Tests

- [x] generator determinism + difficulty scaling
- [x] verifier determinism + sandbox guards
- [x] DSL parse / print round-trip
- [x] DSL semantics (all operators)
- [x] baselines return SolveOutput
- [x] runner end-to-end (30 runs, brute solves d=1)
- [x] total: 129 tests passing, ruff clean, mypy clean

### First Experiment

- [x] `docs/reports/synth-v0.1-first-run.md`
- [x] `docs/reports/synth-v0.1-first-run-runs.json`
- [x] `docs/reports/synth-v0.1-first-run-metrics.csv`
- [x] experiment `exp-baf77c8aa95d`: d1-3, 5 instances, 2 systems
- [x] difficulty discrimination verified (brute 100%→60%, random 80%→20%)
- [x] design doc Risk 1 validated (brute-forceable d1-2, partial d3)


---

# First 10 Issues

建议建仓库后直接创建以下 issues：

1. `repo: bootstrap Python project and CI`
2. `protocol: define core Pydantic models`
3. `protocol: implement canonical serialization`
4. `protocol: add stable object hashing`
5. `challenge: implement CSP-v0.1 generator`
6. `verifier: implement CSP deterministic verifier`
7. `baseline: implement random CSP solver`
8. `baseline: implement Z3 CSP solver`
9. `arena: implement benchmark runner`
10. `report: export first benchmark metrics`

---

# Definition of Done

任何新 Challenge 必须同时拥有：

- generator
- verifier
- tests
- baseline
- difficulty definition
- metrics
- reproducibility instructions

任何模型系统都不能绕过统一 verifier。
