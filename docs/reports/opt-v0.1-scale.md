# OPT-v0.1 Scaled Run Report

**Challenge**: `opt-v0.1` (generator_version `0.1.0`)
**Date**: 2026-08-10
**Experiment**: `opt-v0.1-scale`
**Difficulties**: 1, 2, 3, 4, 5
**Instances**: 200 per difficulty (1000 instances, 3600 runs)
**Systems**: `opt-random`, `opt-edd`, `opt-brute`, `opt-dp`
**Experiment seed**: 42
**Database**: `/tmp/vica-opt-scale.db`

> 本报告是 Phase 4 Optimization Arena（OPT-v0.1）的规模化验收实验，把性质上从
> **二元正确性扩展到连续 Solution Quality**。任务为单机总迟到调度 `1||ΣT_j`
> （NP-hard），score = `-ΣT_j`（越大越好，0 = 零迟到）。
> `opt-dp` 精确基准使用位掩码（Held-Karp 式）DP，复杂度 O(n·2^n)（见
> `opt-v0.1-design.md` §7 算法说明）。
> 目标是完成 design doc §10 的 DoD（≥1000 实例 + 报告），研究 `Quality / Cost`。

---

## 1. 实验配置

| d | n | p_max | deadline ratio | 系统 |
|---|----|-------|----------------|------|
| 1 | 6  | 10 | 0.60–1.20 | random, edd, brute, dp |
| 2 | 8  | 20 | 0.50–1.00 | random, edd, brute, dp |
| 3 | 10 | 30 | 0.40–0.90 | random, edd, brute, dp |
| 4 | 12 | 40 | 0.30–0.80 | random, edd, dp（brute 穷举 12! 超时，跳过） |
| 5 | 14 | 50 | 0.25–0.75 | random, edd, dp（brute 穷举 14! 超时，跳过） |

brute 在 d4/d5 因排列空间爆炸（12!/14!）不可行，dp 作为精确基线参照。

## 2. 绝对 Score（总迟到，越低越好）

| d | opt-dp | opt-brute | opt-edd | opt-random |
|---|-------:|----------:|--------:|-----------:|
| 1 | -0.3   | -0.3      | -0.3    | -6.2       |
| 2 | -7.4   | -7.4      | -9.0    | -40.7      |
| 3 | -41.7  | -41.7     | -57.3   | -142.5     |
| 4 | -146.3 | —         | -215.6  | -402.2     |
| 5 | -296.5 | —         | -446.6  | -746.4     |

```text
mean score by (difficulty, system); 200 instances each
```

## 3. 归一化 Quality（相对最优比，1=最优，0=随机最差）

`(score - worst_random) / (best - worst_random)`，best 取 dp/brute 精确解，worst 取该
challenge 上随机基线的观测最低分。

| d | opt-dp | opt-brute | opt-edd | opt-random |
|---|-------:|----------:|--------:|-----------:|
| 1 | 100.0% | 100.0%    | 99.9%   | 20.5%      |
| 2 | 100.0% | 100.0%    | 89.5%   | 1.0%       |
| 3 | 100.0% | 100.0%    | 76.2%   | 0.5%       |
| 4 | 100.0% | —         | 66.1%   | 0.0%       |
| 5 | 100.0% | —         | 60.7%   | 0.0%       |

**Quality 单调性**：edd 的质量随难度稳步下降（99.9% → 89.5% → 76.2% → 66.1% → 60.7%），
正确反映难度递增。random 在 d2 起即趋近 0（约等于最差随机），说明随机排列在 deadline
收紧后几乎必然远离最优——**难度区分度显著**。

## 4. 精确基线一致性

- **dp ≡ brute**（d1–d3 完全一致）：dp 位掩码（Held-Karp 式）精确解与穷举精确解在
  score 上逐实例一致，验证 DP 实现正确。
- **dp 极快**：d5 平均 10.6ms；brute 在 d3 需 1.1s，d4/d5 不可行。dp 作为精确解基线
  优雅地扩展了可精确求解的规模上限。

## 5. Regret（相对精确解的绝对差距）

**研究指标修正**：早期版本使用 `QC = mean(|score|) / mean(ms)` 作为 Quality。该指标是
**错误的**——因为 `score = -ΣT_j`，`abs(score)` 越大表示解越差，`abs(score)/time` 因此
会**奖励更差的解**。此定义已废弃（`previous QC metric invalidated`）。本报告改为：

```text
regret = optimal_score - candidate_score    （0 = 最优，越大越差）
```

其中 `optimal_score` 由精确位掩码 DP（`opt-dp`）给出。以下 regret 由 §2 的有效 mean score
重算（分数本身未被污染，仅 QC 指标无效）。

| d | opt-dp | opt-brute | opt-edd | opt-random |
|---|-------:|----------:|--------:|-----------:|
| 1 | 0.0    | 0.0       | 0.0     | 5.9        |
| 2 | 0.0    | 0.0       | 1.6     | 33.3       |
| 3 | 0.0    | 0.0       | 15.6    | 100.8      |
| 4 | 0.0    | —         | 69.3    | 255.9      |
| 5 | 0.0    | —         | 150.1   | 449.9      |

```text
regret（平均，迟到期单位）；dp 恒为 0（精确最优），edd/random 随难度单调增大
```

**解读**：dp 的 regret 恒为 0（精确解）；edd 的 regret 随难度单调上升（0 → 1.6 → 15.6 →
69.3 → 150.1），刻画 deadline 收紧后贪心与最优的差距；random 的 regret 在 d2 起即远超
edd，说明随机排列在 deadline 收紧后几乎必然远离最优——**难度区分度显著**。

## 6. Quality 与 Cost 是两个正交维度

本报告不在 Quality 与 Cost 之间强行压缩成一个单值（`abs(score)/time` 之类的公式会掩盖
trade-off 并可能误导）。按设计（`opt-v0.1-design.md`、SPEC "Cost semantics"）分别呈现：

- **Quality**：§3 实验相对归一化 + §5 regret（绝对差距）。
- **Cost**：§6 求解耗时；`estimated_cost_usd` 未配置时为 UNKNOWN（N/A），不当作 0。

`Cost`（edd/random 求解近零成本）与 `Quality`（dp 精确、edd 递减、random 趋零）是独立的
两个维度；arena 保留多维 trade-off，不预设"谁更优"的唯一排序。

## 7. 求解成本

```text
dp:   d1 0.0ms → d5 10.6ms（精确）
brute:d1 0.2ms → d3 1098ms，d4/d5 不可行
edd/random: 均为 ~0ms
```

`Solve Cost >> Verify Cost` 成立：验证为 O(n) 累计，全部在微秒级。

## 8. DoD 对照（design doc §10）

| 验收项 | 状态 |
|--------|------|
| 相同 seed 生成相同 challenge | ✅ |
| verifier 对 (challenge, candidate) 完全确定 | ✅ |
| malformed candidate 不 crash | ✅ |
| 4 个 baselines 可运行并通过统一 verifier | ✅（d4/d5 brute 按设计跳过） |
| ≥1000 实例实验 + 报告 | ✅ 1000 实例（3600 runs） |
| pytest 全绿 | ✅ |

## 9. 结论与下一步

- **OPT-v0.1 达到 Phase 4 DoD**：1000 实例、4 系统、连续 score 的难度区分度显著，
  完成 Quality 与 Cost 多维度度量。
- **关键结果**：
  1. dp 以毫秒级成本给出精确解，明显优于 edd 贪心（d5 质量 60.7% vs 100%）与 random（≈0）。
  2. 传统启发式 edd 在 deadline 收紧时质量单调退化，构成"有挑战但可逼近"的难度梯度。
  3. 穷举 brute 在 d3 起即成本失控，凸显对启发式/通用方法（如 LLM）的价值空间。
- **下一步（Phase 5 候选）**：
  1. 接入 LLM 系统到 OPT（`llm-one-shot` / `llm-agent` 输出调度排列），观察通用模型
     在连续 Quality 上的表现——这是从 SYNTH（正确性）到 OPT（Quality/Cost）的延续。
  2. 校准难度：确认 edd 质量梯度（60–100%）是否可作为稳定的区分度基准。