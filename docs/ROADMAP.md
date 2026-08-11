# VICA Roadmap

路线原则：

> 先验证“可验证智能任务是否成立”，再建设平台；先有实验数据，再定义指标；先攻击 Challenge，再扩大生态。

## 当前研究状态（v0.1.0 Freeze / v0.2.0 Benchmark Research）

### 版本定位

```text
v0.1.0 = Research Integrity / Protocol Foundation Freeze
v0.2.0 = Benchmark Research & External Evaluation
```

v0.1.0 已冻结可信基础设施：deterministic verifier、challenge identity、
verifier-material binding、canonical serialization、SQLite experiment storage、
experiment-scoped system config、cost UNKNOWN 语义，以及 CSP/SYNTH/OPT 三个
Challenge Family 与 LLM adapter。

v0.2.0 转向研究 question：

> VICA 是否能够让未知的外部 Solver / Coding Agent 在隔离的公开 Challenge 上求解，
> 再由权威 Verifier 确定性验证，并产生任何第三方都能重新验证的 Benchmark
> Result Bundle？

核心闭环：Prepare → Public Bundle → External Solver → Submission Bundle →
Authoritative Verification → Result Bundle → Independent Reverification →
Benchmark Research Report。

### 成熟度声明

仓库中已有 SYNTH-v0.1 / OPT-v0.1 / OS 沙箱的**代码 prototype**，但这**不**等于
对应 Phase 已完成。Roadmap 里的 Phase 表示**研究成熟度与正式退出条件**；代码
prototype ≠ milestone complete。当前把它们标为 *Experimental / Under Review*，
只有满足退出条件并经过外部复核后才算完成。v0.2.0 **不**把 SYNTH / OPT / OS
沙箱升级为 Stable。

Public API / hosted arena（Phase 6）是**有意延期**（intentional deferral），
在 challenge integrity 与 reproducibility 成熟之前不实施，这并非缺失功能。

---

## Phase 0 — Protocol Foundation

目标：建立最小、稳定、可测试的协议层。

交付：

- Challenge schema
- Candidate schema
- Result schema
- Canonical serialization
- ChallengeFamily interface
- SolverSystem interface
- Benchmark Runner skeleton
- SQLite storage
- test suite

退出条件：

- deterministic tests 全部通过
- 同一 experiment 可重复运行

---

## Phase 1 — CSP Local Arena

目标：跑通首个完整闭环。

交付：

- CSP-v0.1 generator
- CSP verifier
- Random baseline
- Traditional solver baseline
- Difficulty presets
- 1,000-instance benchmark
- CSV / JSON export

关键问题：

> CSP 是否仅仅被专用 Solver 碾压？

预期：

很可能是。

意义：

验证基础设施，并建立“主动证明 Challenge 不够好”的研发文化。

---

## Phase 2 — Model Arena

目标：让模型系统和传统算法进入同一 Benchmark。

交付：

- Local model adapter
- 一个商业 API adapter
- budget / timeout control
- token accounting
- cost accounting
- retry strategy abstraction

核心输出：

- Success Rate
- $ / Valid Solution
- Valid Solutions / Dollar
- Latency distribution
- Difficulty curves

退出条件：

至少得到一份可复现的跨系统实验报告。

---

## Phase 3 — Program Synthesis v0.1

目标：进入真正可能具有智能区分度的任务族。

交付：

- SYNTH-v0.1 generator
- public tests
- hidden tests
- candidate program format
- compiler/runtime adapter
- secure sandbox
- timeout / memory / syscall limits
- LLM coding-agent baseline
- brute-force / enumerative baseline

重点验证：

```text
Solve Cost >> Verify Cost
```

以及：

```text
general-purpose reasoning advantage?
```

---

## Phase 4 — Optimization Arena

目标：从二元正确性扩展到连续 Solution Quality。

任务候选：

- Scheduling
- Packing
- Assignment
- Graph problems
- Planning
- Resource allocation

交付：

- OPT-v0.1
- objective score
- feasibility verifier
- score threshold difficulty
- Quality / Dollar metrics

---

## Phase 5 — Challenge Research Lab

目标：从工程项目进入系统性研究。

每种 Challenge 必须同时有：

1. generator
2. verifier
3. naive baseline
4. specialized baseline
5. attack notes
6. difficulty calibration
7. benchmark report

建立：

```text
docs/challenge-research/
```

记录：

- 已淘汰任务
- 被发现的 shortcut
- 模型特定 exploit
- 数据泄漏风险
- solver dominance
- generalization 失败案例

---

## v0.2.0 — Benchmark Research & External Evaluation

将工程 benchmark 升级为研究 benchmark，并让未知外部 Solver 参与同一权威 Verifier。

交付（M1–M6）：

- M1 v0.1 Release Baseline / v0.2 Workspace
- M2 Evaluation Bundle（public/private 分离、manifest hash、`vica eval prepare/inspect`）
- M3 External Solver Protocol（file exchange + command solver、Submission Bundle）
- M4 Result Bundle + deterministic Reverify（`vica eval verify` / `vica reverify`）
- M5 Benchmark Methodology（Wilson 95% CI、cost coverage、latency、failure taxonomy、paired comparison）
- M6 SYNTH Scientific Calibration / Challenge Research Lab

原则：

```text
1. Solver output is untrusted.
2. Correctness remains deterministic.
3. No LLM judge.
4. External Solver 与内置 Solver 进入同一个 verifier。
5. Public Bundle 绝不包含 verifier secret / hidden tests / reference target。
6. Result Bundle 可重新验证。
7. UNKNOWN cost 保持 UNKNOWN。
8. Historical benchmark data 不被新逻辑悄悄重解释。
9. Challenge generator version 改变语义时升版本。
10. Benchmark 允许“不支持原假设”的结论。
```

v0.2.0 明确**不**做：Server / FastAPI / Hosted Arena / Public API / Web UI /
账号登录 / 在线排行榜 / Worker scheduler / P2P / Blockchain / Token / Wallet。

---

## Phase 6 — Public Arena

只有 Challenge 足够成熟之后再做。

交付：

- Public Challenge API
- Submission API
- SDK
- authentication
- rate limiting
- leaderboard
- experiment pages
- reproducible result bundles

原则：

排行榜必须展示多维指标，而不是制造单一“总分”。

---

## Phase 7 — Distributed Execution Research

可选长期方向。

研究：

- remote workers
- task scheduling
- result verification
- reputation
- worker capability profiling
- cost-aware routing

此阶段依然不自动意味着需要区块链。

---

## Go / Pivot / No-Go

### GO

至少一种任务族满足：

- Solve Cost 明显高于 Verify Cost
- Difficulty 可预测调节
- 结果客观
- 实例无限或足够大
- 不容易通过缓存/记忆破解
- 多种系统存在稳定效率差异

### PIVOT

如果专用算法普遍击败通用模型：

转向：

**Hybrid Intelligence Arena**

重点研究：

```text
LLM + Solver + Search + Tool Use
```

的最佳组合。

### NO-GO

如果长期无法找到：

```text
Hard-to-Solve
Easy-to-Verify
```

的任务族，或 Benchmark 结果无法复现，则停止扩大平台层。
