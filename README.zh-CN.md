简体中文 | [English](README.md)

# VICA

**Verifiable Intelligence Compute Arena** · 可验证智能计算竞技场

**VICA 1.0 — Research Benchmark Stable**

一个 Local Research Arena，用于度量不同计算系统——LLM、Coding Agent、传统算法与
混合系统——在自动生成、客观可验证任务上的表现。

VICA 不是托管服务。它是一个 **Local Research Arena**：你在本地生成 Challenge、
运行 Solver、并用确定性 Verifier 评估它们。

---

## 核心问题

VICA 研究的不只是"哪个模型聊天最好"，而是：

> 在未知任务、有限时间与有限预算下，哪种计算系统能以最低成本产出最多
> 被确定性验证的高质量解决方案？

设计原则：

- **难解、易验**——计算是成本，验证是廉价的。
- 难度可配置；Challenge 按需生成、无上限。
- Verifier 确定且 Solver 中立——**不使用 LLM 作为裁判**。
- 模型、算法与 Agent 共享同一 Solver 接口与同一 Verifier。
- 成本、延迟、成功率与解质量被统一度量。

---

## 当前状态

VICA 1.0 冻结了以下协议与 Benchmark 表面。它是 **Local Research Arena**——无托管
服务、无在线排行榜、无加固的任意代码沙箱。见 `docs/SPEC.md`「Compatibility Contract」
与 `docs/MIGRATION.md`。

VICA 是 Local Research Arena。以下组件当前已存在：

| 组件 | 状态 | 用途 |
|------|------|------|
| Protocol Core | Stable | Pydantic 模型、canonical 序列化、接口、challenge identity |
| CSP-v0.1 | Stable | 基础设施验证（约束满足） |
| Random baseline | Stable | 地板基线 |
| Z3 baseline | Stable | 传统 Solver 基线 |
| Arena runner | Stable | Challenge 生成 → 求解 → 验证 → 记录 |
| SQLite storage | Stable | 实验、Challenge、系统、运行记录 |
| Export / metrics | Stable | CSV / JSON 导出、聚合指标 |
| LLM adapter | Under Review | OpenAI 兼容 API 路径（定价可选） |
| Evaluation Bundles | Stable | v1/v2 可移植 Evaluation / Submission / Result bundle |
| Strict Reverify | Stable | Result Bundle 的确定性复验 |
| REPO-v0.1 | Stable | Agent Benchmark——coding-agent workspace + patch 验证 |
| Task Pack | Stable | 基准实例集的版本化身份（`task_pack_hash`） |
| Execution Profile | Stable | 环境 provenance（仅记录名称，绝不记录 secret value） |
| Study | Stable | 多 run 复现 + 分层指标（`vica study run`） |
| SYNTH-v0.1 | Experimental | 程序合成研究（受限 DSL） |
| OPT-v0.1 | Experimental | 连续解质量（调度） |
| OS sandbox | Experimental | OS 资源隔离原型（见 Security） |

"Experimental / Under Review" 反映的是研究成熟度，而非仅仅代码是否存在的标志。
`src/vica/server/` 有意保持为空——Public API / hosted arena 被明确延期（见下文）。

---

## 安全

- SYNTH-v0.1 执行的是一个**受限 DSL 解释器**。它**不**执行任意 Python 候选代码
  （无 `exec`、无 `eval`）。
- OS 级沙箱（`src/vica/sandbox/`）是一个**实验性 OS 资源隔离原型**，当前**不应**
  视为已硬化的恶意代码隔离边界。内存限制仅 Linux 生效；网络命名空间 / chroot
  仅 Linux+root 且默认关闭；输出上限是"超限立即 kill 子进程"的有界流式读取
  （硬性强制），而非事后截断。
- 沙箱子进程继承的是一个**最小 allowlist 环境**——默认不把宿主 secrets
  （API 密钥、令牌）传给候选。

## 研究诚信

- 正确性不使用 LLM 裁判——验证是确定性的。
- Verifier Solver 中立——不偏袒任何 Provider 或模型。
- 传统 Solver 压制通用模型是有效的研究结果。
- 可复现性元数据（git commit、VICA 版本、generator 版本、系统配置、
  环境清单、seed）在每个实验中被持久化。
- Challenge identity 由声明输入可复现：普通家族为
  `(type, generator_version, seed, difficulty)`；secret-bound 家族额外包含
  `verifier_material_commitment`（对含 material version 的 domain-separated
  字符串做完整 SHA-256），因此相同 public seed + 不同 verifier material
  得到不同 challenge_id。
- 当提供的 secret 与 Challenge 的 material commitment 不匹配时，verifier
  拒绝执行 hidden 评估：这是 evaluator 配置失败（`INTERNAL_ERROR`，原因
  `verifier_material_mismatch`），绝不是 Solver 的 `INVALID_SOLUTION`。
- 隐藏验证材料（hidden tests、参考解、verifier secret）与 Solver 输入隔离。
  见 `docs/SPEC.md` "Verifier Material"。

> Development Mode 与 Evaluation Mode：直接在仓库根目录工作的 Coding Agent 可以读取
> `src/`。对于真正的对抗性 hidden benchmark，请把 verifier secret / hidden tests /
> 参考解放在 Agent 可读 workspace 之外，只给它一个 public challenge bundle。
>
> Evaluation Mode **保证**：参考 target 与 hidden tests 由 verifier secret
> 绑定（HMAC 派生；仅凭 public seed 无法恢复），Solver 可见的 challenge 从不包含
> verifier material，active evaluator secret 从不写入 Solver 可读的实验 DB，
> 且 secret-bound challenge 会公开承诺其 verifier material，verifier 可在任何
> hidden 评估之前拒绝错误的 secret。
> Evaluation Mode **不保证**：拿到 verifier-private 路径或 secret 本身的 Agent
> 仍可恢复隐藏材料，因此对抗性评估必须把 Solver 放在不含 verifier-private 状态的
> 独立 workspace 中运行。

---

## Challenge Families

| Challenge | 状态 | 用途 |
|-----------|------|------|
| CSP-v0.1 | Baseline | 基础设施验证 |
| SYNTH-v0.1 | Experimental | 程序合成研究 |
| OPT-v0.1 | Experimental | 连续解质量 |

难度级别是**预设参数包**，不是"经过科学校准的通用难度"的声明。

---

## 基准实验

为保留溯源，历史 / 工程验证结果被保留。它们**不**被包装成最终排行榜：

- `docs/reports/csp-v0.1-first-run.md` —— CSP Random vs Z3（基础设施验证）。
- `docs/reports/synth-v0.1-scale.md` —— SYNTH random vs brute（工程验证；早于
  verifier-secret hidden-material 隔离；使用历史 generator `0.1.0`——当前
  post-isolation generator 为 `0.2.0`）。
- `docs/reports/opt-v0.1-scale.md` —— OPT 基线，含精确 DP 参照。

早于 hidden-material 隔离的报告会明确披露：它们不是对抗性 public benchmark。

---

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,solver]"

vica --help
vica version
vica benchmark --challenge csp-v0.1 --difficulty 1-3 --systems random,z3 --instances 1000 --seed 42
vica report <experiment-id>
```

默认数据库位于 `.vica/vica.db`（已被 gitignore），因此全新 clone 不会在仓库根目录
累积运行时产物。

---

## 文档

- [愿景](docs/VISION.md)
- [协议与技术规范](docs/SPEC.md)
- [基准方法论](docs/BENCHMARK_METHODOLOGY.md)
- [Bundle 格式](docs/protocol/BUNDLE.md)
- [路线图](docs/ROADMAP.md)
- [实施任务](docs/TASKS.md)
- [Challenge 研究实验室](docs/challenge-research/README.md)
- 实验报告：`docs/reports/`

---

## 许可

Apache License 2.0。见 [LICENSE](LICENSE)。