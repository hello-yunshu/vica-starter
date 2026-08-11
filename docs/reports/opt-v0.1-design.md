# OPT-v0.1 Design Review

**Status**: Design review passed（编码已完成并通过测试）
**目标**: 优化任务族，从二元正确性扩展到连续 Solution Quality，研究 `Quality / Cost`
（对齐 ROADMAP Phase 4 与设计文档 §17–18）

---

## 1. 任务定义（单机总迟到 Scheduling, `1||ΣT_j`）

给定：

```text
- n 个任务，任务 i 有处理时间 p_i（正整数）与截止期限 d_i（正整数）
```

要求提交一个调度（任务顺序）：

```json
{ "order": [i0, i1, i2, ...] }   // 0..n-1 的一个排列
```

**合法性**（Verifier 客观判定）：

```text
- order 是 0..n-1 的排列（每个任务恰好出现一次）
- 无重复、无越界、无缺漏
```

**Score**（越大越好，最大为 0 表示零迟到）：

```text
完成时间 C_j = 该任务在 order 中累计处理时间
迟到 T_j      = max(0, C_j - d_j)
score(candidate) = - Σ_j T_j
```

`1||ΣT_j` 是 NP-hard；理论上存在伪多项式 DP 精确解，但当前源码的精确 baseline 用的是
位掩码 O(n·2^n) Held-Karp 式 DP（见下方 §7 算法说明）。该任务兼具"连续 score"的研究
价值，又能提供传统精确 baseline 作参照。

---

## 2. 为什么选 `1||ΣT_j`

- **生成简单可复现**：`(seed, difficulty) -> (p_i, d_i)`，纯整数。
- **验证极廉价**：一次 O(n) 累计，绝对确定性。
- **NP-hard**：价值来自"如何排序以最小化总迟到"，不是机械查表。
- **连续 score**：任意排列都有分值，区分度来自"多接近最优"。
- **有分级基线**：random / EDD 贪心 / brute 穷举 / DP 精确，四档递增。

权威 verifier 只判定合法性并计算 `-ΣT_j`，不评判"解好不好"——符合 AGENTS.md
不变式 1（确定性）与 3（不依赖 LLM judge）。

---

## 3. 任务自动生成

```text
Challenge = Gen(type, version, seed, difficulty) -> (p[], d[], budget)
```

生成流程（确定性 PRNG，seed + difficulty）：

1. 从 preset 读取 `n`、`p_range`、`d_ratio`。
2. 随机采样每个任务的 `p_i`。
3. 截止期限 `d_i = round(alpha_i * Σ前驱处理时间)` 或按 `d_ratio` 相对总处理时间生成，
   保证 deadline 有宽有紧，构成非平凡权衡。
4. 保证 `0 < p_i`、`d_i >= 0`；payload 只含 (p, d)，**不含任何参考最优解**。

### Anti-memorization

- 实例由随机 seed 生成，模型无法记忆固定答案。
- DP 参考解只用于校准，从不下发。

---

## 4. Difficulty presets（草案，待校准）

| d | n  | p_range | deadline 生成                | 期望特征         |
|---|----|---------|------------------------------|------------------|
| 1 | 6  | 1–10    | 宽松（多数零迟到）            | trivia，近似 EDD |
| 2 | 8  | 1–20    | 混合宽紧                     | 需局部排序       |
| 3 | 10 | 1–30    | 混合宽紧                     | 搜索空间增大     |
| 4 | 12 | 1–40    | 偏紧                         | 大量迟到，权衡深 |
| 5 | 14 | 1–50    | 偏紧                         | 对启发式构成挑战 |

难度通过 `n`（规模）与 deadline 紧度控制。n 越大，穷举/随机命中"好解"的概率越低。

---

## 5. Deterministic Verifier

```text
candidate -> schema check -> permutation check -> 累计完成时间 -> 迟到 -> score
```

- 同一 `(challenge, candidate)` 永远得到同一 `(valid, score)`。
- Malformed candidate 永不 crash，映射到稳定 ErrorCode。
- 不使用 LLM Judge。

---

## 6. 候选校验规则（ErrorCode 映射）

| 情况 | ErrorCode |
|------|-----------|
| candidate 不是 dict / 缺 `order` | `INVALID_SCHEMA` |
| `order` 不是长度 n 的列表 | `INVALID_SCHEMA` |
| 元素非整数 / 越界 / 重复 / 缺漏 | `INVALID_SCHEMA` |
| 合法排列 | valid=True, score=-ΣT_j |

---

## 7. Baselines（每条必须同时开发）

| 名字 | 策略 |
|------|------|
| `opt-random` | 随机排列（floor baseline） |
| `opt-edd` | 按截止期限升序贪心（传统启发式，对 `Lmax` 最优但对 `ΣT` 非最优） |
| `opt-brute` | 穷举所有排列取最优（n 小时精确，n 大时超时） |
| `opt-dp` | 位掩码（Held-Karp 式）DP 精确解，O(n·2^n)，n≤~20 可行 |

> **算法说明（与源码一致）**：`opt-dp`（`systems/opt/dp.py`）实现的是位掩码
> Held-Karp 式精确 DP——对每个已用子集 mask 记录最小 ΣT：
>
> ```text
> dp[mask] = min over j in mask of dp[mask ^ (1<<j)] + max(0, time[mask] - d_j)
> time[mask]  = mask 内任务处理时间之和（该子集最后任务的完成时间）
> 答案       = dp[全量 mask]
> ```
>
> 复杂度为 **O(n · 2^n)**，不是伪多项式 O(n·P)。`1||ΣT_j` 存在"按时完工任务按 EDD
> 排序"的最优调度（Lawler 精确算法的理论依据），但当前源码**未**采用该 EDD 顺序上的
> 背包式伪多项式 DP；代码与 brute 在小规模（n≤12)上逐例一致，作为可信精确基准。

---

## 8. 衡量指标

沿用整套指标，额外关注：

```text
- Quality / Cost            （Optimization Challenge 核心，设计文档 §27）
- score 分布（p50 / p95 score）
- 相对最优比 = (score - 随机)/ (最优 - 随机)  （校准用，不下发）
- 迟到任务数分布
```

---

## 9. 已知风险

| 风险 | 缓解 |
|------|------|
| DP 精确解碾压通用模型 | 正是文档 Risk 1 场景；若成立转向 Hybrid（PIVOT）。v0.1 先记录数据 |
| score 区分度不足        | 提高 n / 收紧 deadline，扩大搜索空间 |
| 随机基线可轻易构造合法解 | 合法解 easy 是特性；区分度在 score 而非合法率 |
| deadline 生成导致平凡最优 | 混合宽紧 deadline，避免全宽松或全紧 |
| 排列校验的越界/重复攻击 | 集合校验 + 长度上限，超限记为 `SANDBOX_ERROR` |

---

## 10. 验收标准（DoD）

- [x] 相同 seed 生成相同 challenge
- [x] verifier 对 (challenge, candidate) 完全确定
- [x] malformed candidate 不 crash
- [x] 4 个 baselines 可运行并通过统一 verifier
- [x] 至少 1000 实例实验 + 报告（见 `opt-v0.1-scale.md`）
- [x] pytest 全绿

---

## 11. 决定与开放问题

1. ✅ 任务族：单机 Scheduling `1||ΣT_j`（用户确认）
2. ✅ 加入 DP 精确解 baseline（用户确认）
3. ❓ difficulty presets 参数包（n: 6/8/10/12/14）是否合理
4. ❓ score 是否归一化（倾向：不归一，保留绝对负迟到分值）
5. ❓ deadline 生成的具体规则（倾向：按 `d_ratio` 相对总处理时间混合宽紧）