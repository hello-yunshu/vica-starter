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

要求（状态如实校准，见 `docs/SPEC.md` §14）：

- [x] CPU time limit
- [x] wall time limit
- [x] process limit
- [x] fd / core / file-size limit
- [x] cleanup after execution（进程组 kill 清理 fork 出的孙进程）
- [x] 最小 allowlist 环境（不继承宿主 secrets）
- [~] memory limit — 仅 Linux 生效（RLIMIT_AS/DATA）；macOS 上 fork 子进程继承
      约 400GiB 虚拟足迹，macOS 内存隔离交由未来容器 / sandbox-exec 后端
- [x] output limit — bounded streaming read（`select`）结合输出字节预算，超限立即
      SIGKILL 整个进程组；真实硬性资源限制，非事后截断（`SANDBOX_ERROR`）
- [ ] network disabled — 仅 Linux + root 的 `unshare(CLONE_NEWNET)`，默认关闭；
      非 root / macOS 跳过并告警
- [~] read-only minimal filesystem — 仅 Linux + root 的 chroot，默认关闭
- [ ] syscall restriction / container isolation — 未实现（非受限容器后端）

实现：`src/vica/sandbox/`（`run_sandboxed` + `SandboxLimits`），
`tests/test_sandbox.py`。

跨平台说明（macOS 开发机 + Linux CI）：

- CPU / wall / output(硬性流式) / fd / core / process 限制在所有平台生效。
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
> 解释器级沙箱守卫已在 M10 中实现并通过测试。M9 的 OS 级沙箱是**实验性 OS
> 资源隔离原型**，目前不构成已硬化的恶意代码隔离边界；其网络/文件系统/内存/
> syscall 项未可靠完成，故保持 `[ ]` / `[~]`，不标 `[x]`。

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

- [x] deterministic hidden test regeneration: `HMAC-SHA256(verifier_secret,
      type:version:hidden:seed:difficulty)`——固定 secret 完全确定，不同 secret 不同；
      仅公开 (seed, difficulty) 无法重建
- [x] candidate schema check
- [x] parse / eval error mapping to ErrorCode
- [x] sandbox limit mapping to ErrorCode.SANDBOX_ERROR
- [x] malformed input never crashes verifier
- [x] hidden material 隔离：solver 只拿 public challenge，拿不到
      verifier secret / hidden tests / target program（见下方 SYNTH DoD）

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

### SYNTH DoD — hidden-material integrity（Research Integrity & Stabilization Freeze）

- [x] verifier-only hidden material 不能从 solver-visible challenge 数据单独推导
      （`test_public_seed_alone_cannot_reconstruct_hidden_tests`）
- [x] solver 收到的对象不含 reference solution / hidden tests / verifier secret
      （`test_solver_challenge_dict_has_no_secret_or_hidden_material`、
      `test_payload_contains_no_target_or_hidden_tests`）
- [x] adversarial leakage test：公开自检通过但权威 verifier（带 secret）拒绝的
      overfit candidate（`test_authoritative_verifier_rejects_when_solver_selfcheck_accepts`）
- [x] 同 secret + 同 challenge => 相同 hidden material；不同 secret => 不同
      （`test_hidden_tests_regenerate_identically`、
      `test_different_verifier_secret_yields_different_hidden_tests`）


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

---

# v0.1 Stabilization Freeze（Research Integrity & Stabilization）

状态如实标注；`[~]` 表示仅部分/需外部条件保证。

## Evaluation Mode / 隐藏材料

- [x] reference target 由 `HMAC-SHA256(verifier_secret, type:version:target:seed:difficulty)`
      派生，仅凭 public (seed, difficulty) 无法恢复
- [x] hidden tests 使用独立 domain tag（`hidden`），与 target RNG 域分离
- [x] Solver-visible challenge 不含 verifier material（target / hidden / secret）
- [x] active evaluator secret 不写入 solver-readable 实验 DB
      （experiments.config_json 只存公开 material 引用：完整 commitment +
      verifier_material_id/version）
- [~] 对抗性 Evaluation Mode 需要 Solver 运行在**不含 verifier-private 状态**的
      独立 workspace / 容器中（见 `docs/SPEC.md` §14bis 与 README）。v0.1 定义
      public-bundle **边界**（solver-visible challenge 携带 commitment，绝不携带
      secret / target / hidden），并提供 verifier-private 路径 + 显式 secret；
      **由 evaluator 负责**把 solver-visible challenge 放入隔离 workspace。
      v0.1 不提供独立的 public-bundle CLI 工具，也不做 OS 用户隔离

## Metrics / 成本 / 错误语义

- [x] UNKNOWN cost 一律 N/A，`vica report` / leaderboard 不 crash
- [x] LLM transport 语义稳定：success / timeout / transport_error /
      provider_error / parse_error / no_candidate；
      timeout → TIMEOUT；transport/provider error → INTERNAL_ERROR；
      parse_error / no_candidate → INVALID_SOLUTION
- [x] OPT regret（optimal - candidate）正确方向；不再使用 `abs(score)/time` 作为
      quality
- [x] system config 为 experiment-scoped 快照（`experiment_systems` 表，v2 schema，
      `PRAGMA user_version` 迁移）

## Provenance

- [x] `scripts/llm_verify.py` 走权威 `verify_submission`（含 hidden tests），
      所有 solver（llm / brute / random）同一判定路径
- [x] 开发脚本统一从 `scripts/_dev_config.py` 读取 dev verifier secret
      （`VICA_DEV_VERIFIER_SECRET` 可覆盖），明确 NON-SECRET DEV ONLY

---

# v0.1 Final Freeze — Protocol Identity & Release-Candidate

- [x] secret-bound Challenge 携带公开 `verifier_material_commitment`
      （完整 64 hex SHA-256，domain-separated，含 material version）
- [x] commitment 进入 Challenge identity（相同 seed / difficulty / version +
      不同 material => 不同 challenge_id；CSP / OPT 普通 identity 不受影响）
- [x] verifier 在 hidden 评估前首先校验 commitment；mismatch / 缺失 secret
      => `INTERNAL_ERROR`（日志标注 `verifier_material_mismatch`），绝不误报为
      Solver 的 `INVALID_SOLUTION`
- [x] SYNTH post-isolation generator 版本升级（`0.2.0`，与历史 `0.1.0` 区分；
      历史报告保留原版本标注并说明 predate isolation）
- [x] 真实 legacy schema（origin/main 的 `experiments` 无 `env_json`、
      无 `experiment_systems`）迁移验证：v0→v1（补 `env_json`）→v2
      （建 `experiment_systems`），历史行保持、迁移后新写入成功、重开幂等
- [x] LLM `max_retries=0` 与显式 `timeout_seconds` 以 `is not None` 判定，
      不退回环境默认值；`max_retries >= 0`、`timeout_seconds > 0` 校验
- [x] `work/v0.1-freeze-final` 以 `origin/main` 为祖先（存在合法 merge-base）
- [x] 最终 PR（base: main, head: work/v0.1-freeze-final）在新 merge ref 上
      CI 全绿（Install / Ruff / mypy / pytest）

未完成项不得提前勾选。

---

# v0.2.0 — Benchmark Research & External Evaluation

> v0.1.0 = Research Integrity / Protocol Foundation Freeze
> v0.2.0 = Benchmark Research & External Evaluation

## Milestone M1 — v0.2 Workspace

- [x] 从最新 `main` 创建 `work/v0.2-benchmark-research`
- [x] ROADMAP / TASKS / SPEC 版本定位更新（v0.1 Freeze / v0.2 Bench Research）

## Milestone M2 — Evaluation Bundle

- [x] `vica eval prepare`：生成 public+private 分离的 Evaluation Bundle
- [x] Public Bundle：evaluation_id / bundle_format_version / challenge_type /
      generator_version / seed / difficulty / challenge_id /
      verifier_material_commitment / public payload / challenges_hash
- [x] Private Bundle：verifier_material_commitment / verifier_material_id /
      verifier_secret（0600），保持最小（不重复保存 hidden tests）
- [x] manifest_hash = SHA-256(canonical manifest without hash)，用
      `vica.protocol.serialization`
- [x] `vica eval inspect`：manifest parse / bundle version / challenge count /
      重复 id / public-private 一致性 / manifest hash / tamper 检测
- [x] 安全边界文档：public/private 是 evaluator bundle organization，非 OS 隔离；
      Coding Agent 只能拿 `public/`

## Milestone M3 — External Solver Protocol

- [x] File Exchange（Mode A）：solver 读 public challenges → 写 `submissions.jsonl`
- [x] Command Solver（Mode B）：`vica solver run --command ...`，stdin→challenge，
      stdout→candidate
- [x] Submission Bundle：manifest（evaluation_id / system_id / created_at）+
      submissions.jsonl
- [x] 基础验证：unknown challenge id → reject；missing challenge → NO_SUBMISSION；
      duplicate challenge id → reject ambiguous input
- [x] NO_SUBMISSION 与 INVALID_SOLUTION 在报告层区分
- [x] 单条 malformed candidate 不丢弃整批（per-instance failure）
- [x] candidate JSON schema 错误 → INVALID_SCHEMA 进入结果

## Milestone M4 — Result Bundle + Reverify

- [x] `vica eval verify`：load public + private → 校验 hash → match challenge_id →
      reconstruct Challenge → 校验 material commitment → 权威 `verify_submission()`
- [x] 复用 `verify_submission()`，不建第二套 verifier
- [x] Result Bundle：manifest / evaluation.json / system.json / environment.json /
      challenges.jsonl / submissions.jsonl / results.jsonl / metrics.json / report.md
- [x] Result Bundle 记录：bundle_format_version / evaluation manifest hash / VICA
      version / git commit / generator version / commitment / system / raw
      submissions / raw results / metrics / environment
- [x] Result Bundle 不含 verifier secret / hidden tests（无泄漏测试）
- [x] Result Bundle manifest 含 bundle_hash / 各文件 sha256（tamper 检测）
- [x] `vica reverify <result-bundle> --evaluation <eval>`：strict reverify
      （same generator version / commitment / challenge id），不重新调用 Solver
- [x] evaluator-level 错误（wrong private material / corrupt private / hash
      mismatch / unknown generator）与 solver outcome 分离

## Milestone M5 — Benchmark Methodology

- [x] `docs/BENCHMARK_METHODOLOGY.md`
- [x] `docs/protocol/BUNDLE.md`（Bundle 格式）
- [x] Wilson 95% CI（标准库实现，不依赖 SciPy）
- [x] latency：mean / p50 / p95
- [x] cost：known cost coverage = known / total
- [x] failure taxonomy：valid / invalid_solution / timeout / transport_error /
      provider_error / parse_error / no_candidate / no_submission /
      sandbox_error / internal_error / unsupported
- [x] failure report：counts / rates / by difficulty
- [x] paired comparison（A wins / B wins / tie / both fail）
- [x] answer-first `report.md`：Evaluation / System / Challenges / Valid rate /
      95% CI / Latency / cost coverage / main failure modes / OPT regret
- [x] 不做排行榜幻觉：默认 per-family / per-difficulty / per-metric 输出

## Milestone M6 — SYNTH Calibration / Challenge Research Lab

- [x] `docs/challenge-research/README.md`
- [x] SYNTH shortcut audit / difficulty calibration / generalization /
      solver dominance 文档（无数据时如实写 Not Yet Established）
- [x] ambiguity probe 方法文档（public tests 是否足以约束 target）
- [x] Go / Pivot / No-Go 退出条件

## 测试与门禁

- [x] Evaluation Bundle / Manifest integrity / External Solver protocol /
      Submission Bundle / Authoritative verify / Result Bundle / Reverify /
      Statistics / Failure taxonomy 测试全部新增
- [x] 回归门禁 PASS：`ruff check .` / `mypy src` / `pytest -q`（旧 Research
      Integrity 测试未删除）
- [x] E2E：CSP + SYNTH + OPT 各跑通 prepare → submit → verify → bundle → reverify
- [x] CLI smoke：prepare / solver run / verify / reverify / inspect / tamper
- [x] private material 不泄漏进 public bundle（grep 验证）
- [x] 确认无工作提示词、无 runtime DB 提交

未完成项不得提前勾选。

---

# v0.3.0 — Agent Benchmark（REPO-v0.1）

> v0.2.0 = Benchmark Research & External Evaluation
> v0.3.0 = Agent Benchmark（REPO-v0.1）

## Milestone R1 — REPO-v0.1 Family

- [x] 从最新 `main` 创建 `work/v0.3-agent-benchmark`
- [x] ROADMAP / TASKS / SPEC 版本定位更新（v0.3 Agent Benchmark）
- [x] `repo-v0.1` Challenge Family（generator `0.1.0`，`task_kind`：
      `repair` / `implementation`）
- [x] Workspace 对象：identity hash（`workspace_hash`）+ safety（拒绝绝对路径 /
      `..` / symlink escape / device/FIFO/socket / nested `.git`）
- [x] Patch Candidate：git unified diff，`MAX_PATCH_BYTES` / `MAX_CHANGED_FILES` /
      `MAX_CHANGED_LINES`，text-only
- [x] 6 个 task templates：`parser` / `cache` / `state_machine` / `serialization` /
      `scheduler` / `storage`（`repair` + `implementation`）
- [x] Secret-bound hidden verification（HMAC-SHA256，domain-separated；public =
      buggy==fixed，hidden = buggy!=fixed）
- [x] 生成 >= 24 distinct benchmark instances（survey 120 实例，100 distinct
      workspace hash；reference 100% pass / NoOp 100% hidden-fail）

## Milestone R2 — Bundle v2 + Dispatcher

- [x] Evaluation / Submission / Result Bundle **v2** 版本常量
- [x] Bundle Dispatcher（`load_*_v1` / `load_*_v2`），v1 artifact 仍按 v1 reader
      解释，不静默重解释
- [x] `vica eval prepare` 支持 REPO（materialize workspace 于 public/）
- [x] submission / result 的 bundle version 随 evaluation version 对齐

## Milestone R3 — Agent Mode

- [x] `vica agent run`：copy workspace → 在 scratch 内运行 Agent（cwd）→ 捕获
      patch → 写 Submission Bundle → 删除 scratch
- [x] `vica agent noop`（空 patch 基线，必须 fail hidden）
- [x] `vica agent reference`（权威 patch 基线，必须 100% pass）
- [x] Agent 环境 allowlist；`--pass-env` 显式转发；`VICA_VERIFIER_SECRET` /
      `VICA_PRIVATE_*` 永不透传（即使误请求也拒绝）
- [x] per-task timeout / nonzero exit / no patch / patch too large 区分，不全部
      归为 NO_SUBMISSION

## Milestone R4 — REPO Verifier + Reverify

- [x] REPO Verifier 流程：validate workspace hash → validate patch → materialize
      到 temp（绝不改原始）→ apply patch → structural → public → hidden →
      deterministic result
- [x] 新 Failure Taxonomy：`PATCH_APPLY_FAILURE` / `STRUCTURAL_VIOLATION` /
      `PUBLIC_TEST_FAILURE` / `HIDDEN_TEST_FAILURE` 等
- [x] patched code 在 `vica.sandbox` 运行（直接调用 `solve`，非 pytest）
- [x] 结果记录非 secret REPO 事实（workspace_hash / patch_hash / patch_bytes /
      changed_files / changed_lines / task_kind）
- [x] REPO Strict Reverify 绑定 workspace_hash + patch_hash（tamper 检测）

## Milestone R5 — Research Lab + CLI

- [x] `docs/challenge-research/repo/`：README / threat-model / shortcut-audit /
      task-validity / difficulty-calibration
- [x] CLI：`vica eval prepare / inspect / verify`、`vica agent run / noop /
      reference`、`vica reverify`

## 测试与门禁

- [x] Workspace / Patch / Hidden / Agent / Reverify 测试全部新增（`test_repo.py`）
- [x] 回归门禁 PASS：`ruff check .` / `mypy src` / `pytest -q`（0.1/0.2 测试未删除）
- [x] REPO E2E（repair + implementation）+ CSP/SYNTH/OPT regression
- [x] 版本更新 0.3.0（pyproject / __init__ / SPEC / ROADMAP / TASKS / README /
      README.zh-CN / CHANGELOG）

未完成项不得提前勾选。
