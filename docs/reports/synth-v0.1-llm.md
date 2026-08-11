# SYNTH-v0.1 LLM Solver Comparison Report

**Challenge**: `synth-v0.1` (generator_version `0.1.0`)
**Date**: 2026-08-10 (methodology), **revalidated**: 2026-08-11
**Experiment seed**: 42
**Instances**: 50 per difficulty (d3, d4, d5), 150 total
**Systems**: `llm-short` (LLM-style short-expression induction), `synth-brute`, `synth-random`
**Raw data provenance**: `scripts/llm_find.py` (full probe set), `scripts/llm_verify.py` (official-verifier confirmation)

> **⚠ 研究诚信声明（已重新核验）**：本报告最初版本（2026-08-10）的量化结论基于
> **未隔离**的旧 target 生成方案。在 `v0.1 Stabilization` 中，SYNTH 的 reference target 与
> hidden tests 已改为 **verifier-secret 绑定**（HMAC-SHA256，domain-separated，见
> `docs/SPEC.md` "Verifier material"）。**旧报告中的成功率数字（46%/22%/24%、69.7%/59.1%/21.2%）
> 已失效（invalidated）**，因为它们是在旧 target 上过拟合的——《predates current verifier isolation》，
> 见下方"§3 复核结果"与 §4 结论修正。本报告不再声称任何有效的 LLM-vs-基线对比。
> 真实 LLM 对比需在**当前** secret-bound generator 下重新生成 probe set（见 §6）。

> **Generator 版本**：当前 SYNTH 实现使用 `generator_version` **0.2.0**
> （target / hidden / public examples 全部 secret-bound）。本报告所有数字
> 均来自历史 `generator_version` **0.1.0**（target 由 public seed 派生），
> 早于 verifier-material isolation，两者不可直接比较。

> 本报告量化一个核心研究问题：**通用模型（LLM）在程序合成上如何与穷举基线对比？**
> 由于没有真实 API key，我们用两种方式来代表 LLM：一是直接在 cue 上推理（`llm-short`，
> 一种"短表达式第一"的归纳搜索，模拟通用模型先尝试简洁解法的行为）；二是
> `src/vica/systems/llm/llm_solver.py` 中已实现的 `llm-one-shot` / `llm-agent` 真实 API 路径
> （待配置 key 后即可实跑）。

> **研究诚信说明（research-integrity note）**：隐藏测试通过开发脚本（`scripts/llm_verify.py`）
> 使用显式 verifier-secret 访问，用于研究复核（`_dev_config.py`，NON-SECRET DEV），
> `llm-short` 求解器本身只接收公开 payload，不能接触隐藏材料。本报告不构成对抗性公开基准。

---

## 1. 方法：什么是 `llm-short`

`llm-short`（`scripts/llm_find.py`）在假设空间上做一种**有偏的短表达式优先搜索**：

- **小常数池**：从公开测试的输入/期望输出中提取 `[-20, 20]` 的整数作为叶子常数
  （模拟 LLM 从示例中"读"出出现过的数值）。
- **节点预算**：只枚举 ≤ 5 个 AST 节点的表达式。
- **公开测试自检**：找到第一个通过全部 public tests 的表达式即停（`llm-find`），
  再用隐藏测试判定（`_hidden_ok`）。

这与穷举基线 `synth-brute`（枚举到 13 节点 / 约 20 万候选）在**假设空间大小上刻意不对等**，
目的是分离两种能力：**"短表达式归纳"（LLM 风格）vs "穷举生成"（搜索风格）**。

## 2. 全量结果（n=150，每难度 50）——【历史失效，仅供参考】

> ⚠ 下表数字基于**未隔离**的旧 target 生成方案，属于
> `historical engineering validation predates current verifier isolation`，
> **不适用于当前 verifier**。仅保留作历史记录，不得引用为当前研究结论。

| Difficulty | llm-short | synth-brute | synth-random |
|-----------:|----------:|------------:|-------------:|
| 3          | 46%       | 44%         | 16%          |
| 4          | 22%       | 16%         | 7.5%         |
| 5          | 24%       | 18%         | 2.0%         |
| **Overall**| **30.7%** | **26.0%**   | **—**        |

> 注：`synth-random` 在第 1 节的全量校准实验（`/tmp/vica-synth-calib.db`，每难度 200）中
> d3/d4/d5 分别为 16% / 7.5% / 2.0%，此处直接引用。（同为历史失效口径。）

## 3. 在当前 secret-bound verifier 下复核（n=66）——结论修正

`scripts/llm_verify.py` 现在**全部走权威验证器**（`verify_submission` + verifier-secret，
对 llm / brute / random 一视同仁，`build_challenge(..., verifier_secret=...)`），
不再使用 `FAMILY.verify` 或仅公开测试的 `_hidden_ok`。用原始 `scripts/llm_answers.json`
（66 个 llm-short 表达式）在当前 generator 下复核结果：

| System        | passes current public | hidden success |
|---------------|----------------------:|---------------:|
| llm-short（旧答案） | 0 / 66 **(0.0%)** | **0.0%** |
| synth-brute    | —                     | 30.3%          |
| synth-random   | —                     | 7.6%           |

> **为什么是 0%**：`llm_answers.json` 是在**未隔离**的旧 target 上从旧 public tests
> 归纳出的表达式。当前 generator 的 reference target 由 verifier-secret 绑定，旧表达式的
> **public 期望输出已改变**，因此旧答案连当前 public tests 都不匹配（`llm_pub` 全 False），
> 隐藏测试自然全失败。**这不是"LLM 能力差"的结论**，而是数据口径不一致的产物。
>
> 因此本报告**不再声称任何有效的 LLM-vs-基线相对排序**。旧 §3 的 69.7%/59.1%/21.2%
> 与旧 §4 的"llm-short 超过穷举"结论一并 **invalidated**（`predates current verifier isolation`）。
> 要得到有效对比，必须在当前 secret-bound generator 下**重新生成 probe set**（§6）。

## 4. 关键发现（修正后）

1. **当前没有可用的 LLM-vs-基线对比**。旧结论（llm-short 在所有难度超过穷举）已失效，
   因为它建立在未隔离的旧 target 上。任何把 `llm-short`/启发式结果当作"LLM 击败穷举"
   的表述都是不成立的（§8.5：`llm-short` 只是短表达归纳启发式，不是真实 LLM benchmark）。

2. **验证边界已确认生效**：权威验证器确实用 secret-bound 的 hidden material 判定，
   求解器可见的公开 payload 不含任何 verifier material；旧答案在隔离后无法通过
   当前生成器的公开测试，证明"same public seed + 无 secret → 无法恢复 target"的边界成立。

3. **随机基线在 d4–5 几乎失效**（§5 校准口径下 d5 约 2%）：搜索空间对随机命中极不友好，
   这是最接近"对通用方法构成挑战"的难度段。该观察来自 `synth-v0.1-scale.md` 的规模化实验，
   与本文档的 LLM 对比无关。

## 5. 与校准的关系

本实验运行在**校准后**的 d4/d5 预设上（`family.py` 中 d4/d5 增加 `min_nodes` +
`reject_constant`，见 `docs/reports/synth-v0.1-scale.md` 校准小节）。校准消除了旧实验
中 d4 的 brute 反弹（54% → 23%），使难度恢复单调；但**这并不改变 §3 的失效判定**——
校准只影响 target 采样，旧答案仍因 target 改为 secret-bound 而不匹配当前 verifier。

## 6. 局限与下一步

- **局限（决定性）**：现有 probe set（`scripts/llm_answers.json`）在**未隔离**的旧 target 上生成，
  当前 secret-bound verifier 下**不可用**（0/66 通过当前 public tests）。因此本报告**没有
  有效的 LLM-vs-基线对比**；旧数字仅作历史工程验证留存。
- **局限**：`llm-short` 只是"短表达式第一"的归纳启发式，**不是真实 LLM 输出**。
  真实 API 路径（`llm-one-shot` / `llm-agent`）已实现，但需配置 `VICA_LLM_API_KEY` /
  `VICA_LLM_MODEL` 才能实跑，且必须运行在**当前** secret-bound generator 下才有意义。
- **下一步**：
  1. 在当前 generator 下**重新生成 probe set**（用 `scripts/llm_find.py` 等基于当前 public
     tests 重新归纳），再跑 `scripts/llm_verify.py` 得到有效的 llm-vs-brute-vs-random 对比；
     否则不得引用任何"LLM 击败穷举"的结论。
  2. 配置真实 LLM key，跑 `llm-one-shot` / `llm-agent` 与 `llm-short`、`brute` 三方对比。
  3. 继续 Phase 4 的 Optimization Arena（OPT-v0.1）规模化实验。