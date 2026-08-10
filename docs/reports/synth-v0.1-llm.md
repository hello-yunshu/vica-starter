# SYNTH-v0.1 LLM Solver Comparison Report

**Challenge**: `synth-v0.1` (generator_version `0.1.0`)
**Date**: 2026-08-10
**Experiment seed**: 42
**Instances**: 50 per difficulty (d3, d4, d5), 150 total
**Systems**: `llm-short` (LLM-style short-expression induction), `synth-brute`, `synth-random`
**Raw data provenance**: `scripts/llm_find.py` (full probe set), `scripts/llm_verify.py` (official-verifier confirmation)

> 本报告量化一个核心研究问题：**通用模型（LLM）在程序合成上如何与穷举基线对比？**
> 由于没有真实 API key，我们用两种方式来代表 LLM：一是直接在 cue 上推理（`llm-short`，
> 一种"短表达式第一"的归纳搜索，模拟通用模型先尝试简洁解法的行为）；二是
> `src/vica/systems/llm/llm_solver.py` 中已实现的 `llm-one-shot` / `llm-agent` 真实 API 路径
> （待配置 key 后即可实跑）。本报告聚焦可复现的 `llm-short` 对比。

> **研究诚信说明（research-integrity note）**：隐藏测试通过开发脚本（`scripts/llm_verify.py`）
> 使用显式 verifier-secret 访问，用于研究复核；`llm-short` 求解器本身只接收公开 payload，
> 不能接触隐藏材料。本报告度量的是**相对排序**（llm-short vs 穷举 vs 随机），
> 不构成对抗性公开基准。

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

## 2. 全量结果（n=150，每难度 50）

| Difficulty | llm-short | synth-brute | synth-random |
|-----------:|----------:|------------:|-------------:|
| 3          | 46%       | 44%         | 16%          |
| 4          | 22%       | 16%         | 7.5%         |
| 5          | 24%       | 18%         | 2.0%         |
| **Overall**| **30.7%** | **26.0%**   | **—**        |

> 注：`synth-random` 在第 1 节的全量校准实验（`/tmp/vica-synth-calib.db`，每难度 200）中
> d3/d4/d5 分别为 16% / 7.5% / 2.0%，此处直接引用。

## 3. 用官方验证器复核（子集 n=66，仅含 llm-short 找到表达的实例）

`llm_verify.py` 用 `FAMILY.verify`（arena 真值验证器）对 llm-short 找到的 66 个表达式
及其余系统的同一实例进行权威复核：

| System        | Hidden success |
|---------------|---------------:|
| llm-short     | 69.7%          |
| synth-brute   | 59.1%          |
| synth-random  | 21.2%          |

> 该子集存在**幸存者偏差**（只统计 llm-short 找到候选的实例），因此绝对数值偏高，
> 仅用于**交叉验证相对排序**：llm-short > brute > random 在两个口径下一致。

## 4. 关键发现

1. **通用模型式的短表达式归纳，在程序合成上不弱于穷举基线**。
   llm-short 用 ≤5 节点的预算，在三个难度上**全部超过**穷举基线的隐藏测试成功率
   （d3 46% vs 44%，d4 22% vs 16%，d5 24% vs 18%）。这印证了 SYNTH 的设计直觉：
   目标 DSL 表达式的"最小留白"往往很短，短表达式优先的归纳策略比全空间枚举更高效。
   （注：这是"有偏假设空间"的相对优势，不代表 LLM 在绝对能力上碾压搜索。）

2. **穷举基线在 d2 起不再碾压**：与规模化报告一致，brute 的隐藏成功率受
   公开测试过拟合拖累——它枚举到的第一个通过 public tests 的候选常常是"过拟合式"
   的较长表达式，反而不及短归纳找到的简洁解。

3. **随机基线在 d4–5 几乎失效**：d5 仅 2.0%。搜索空间对随机命中极不友好，
   这是最接近"对通用方法构成挑战"的难度段。

## 5. 与校准的关系

本实验运行在**校准后**的 d4/d5 预设上（`family.py` 中 d4/d5 增加 `min_nodes` +
`reject_constant`，见 `docs/reports/synth-v0.1-scale.md` 校准小节）。校准消除了旧实验
中 d4 的 brute 反弹（54% → 23%），使 d4/d5 恢复单调，也让这里的 LLM vs brute 对比
建立在难度单调的基线上，结论更干净。

## 6. 局限与下一步

- **局限**：`llm-short` 是"推理代理"，不是真实 LLM 输出。真实 API 路径
  （`llm-one-shot` / `llm-agent`）已实现但需配置 `VICA_LLM_API_KEY` /
  `VICA_LLM_MODEL` 才能实跑。配置后可用同一 probe set 直接对比，预期
  `llm-agent`（生成-自检-反馈-重试）在 d4–5 上优于 `llm-one-shot`。
- **下一步**：
  1. 配置真实 LLM key，跑 `llm-one-shot` / `llm-agent` 与 `llm-short`、`brute` 三方对比。
  2. 继续 Phase 4 的 Optimization Arena（OPT-v0.1）规模化实验。