# SYNTH-v0.1 Scaled Run Report

**Experiment**: `exp-9925b24b6521`
**Date**: 2026-08-10
**VICA version**: 0.1.0
**Challenge**: `synth-v0.1` (generator_version `0.1.0`)
**Difficulties**: 1, 2, 3, 4, 5
**Instances**: 200 per difficulty (2000 runs total, 1000 instances)
**Systems**: `synth-random`, `synth-brute`
**Experiment seed**: 42
**Raw data**: `synth-v0.1-scale-runs.json`, `synth-v0.1-scale-metrics.csv`
**Database**: `/tmp/vica-synth-scale.db`

> 本报告是 SYNTH-v0.1 的规模化验收实验，把首轮（5 实例）扩展到每难度 200 实例，
> 覆盖全部难度 d1–d5。目标是完成 Phase 3 的 DoD（≥1000 实例实验 + 报告），获得
> 具有统计显著性的 `Difficulty → Success Rate` 曲线，并验证首轮的小样本结论在大样本下是否成立。

> **历史实验状态（research-integrity note）**：本实验及其 d4–d5 难度校准在
> verifier-secret 隔离（hidden-material isolation）落地前完成。当时隐藏测试可从
> 公开的 `(seed, difficulty)` 确定性重建，因此**不能**将该实验视为 adversarial
> public benchmark（对抗性公开基准）。它用于工程闭环验证与难度区分度评估。
> 隐藏材料的 secret-派生隔离见 `docs/SPEC.md` "Verifier material" 与
> `test_synth_generator.py`。

---

## 1. 汇总表

| System        | d | Success | Mean ms | p50 ms | p95 ms | Mean Verify μs |
|---------------|--:|--------:|--------:|-------:|-------:|---------------:|
| synth-brute   | 1 | 100.0%  |    24.8 |    0.2 |  152.7 |           58.2 |
| synth-brute   | 2 |  65.5%  |   234.1 |   49.7 |  791.4 |           41.0 |
| synth-brute   | 3 |  47.5%  |   222.8 |  166.5 |  522.1 |           26.0 |
| synth-brute   | 4 |  54.0%  |   217.6 |    8.3 |  578.3 |           26.6 |
| synth-brute   | 5 |  47.5%  |   231.9 |  233.3 |  490.5 |           25.5 |
| synth-random  | 1 |  81.0%  |     0.8 |    0.5 |    2.6 |           54.8 |
| synth-random  | 2 |  33.5%  |     2.5 |    2.3 |    5.6 |           27.0 |
| synth-random  | 3 |  16.0%  |     3.0 |    3.1 |    4.3 |           17.7 |
| synth-random  | 4 |  24.0%  |     3.4 |    3.6 |    5.8 |           16.2 |
| synth-random  | 5 |  19.0%  |     3.8 |    4.1 |    5.2 |           18.3 |

```text
difficulty=1..5, instances=200 each, seed=42, 2000 runs
```

## 2. Difficulty 曲线

| Difficulty | Operators/Depth/Vars | brute Success | brute Mean ms | random Success |
|-----------:|----------------------|--------------:|--------------:|---------------:|
| 1 | `+ -` / 2 / 1                |        100.0% |          24.8 |          81.0% |
| 2 | `+ - * %` / 3 / 1            |         65.5% |         234.1 |          33.5% |
| 3 | `+ - * % // min max` / 4 / 2 |         47.5% |         222.8 |          16.0% |
| 4 | 全部 + `abs` / 5 / 2         |         54.0% |         217.6 |          24.0% |
| 5 | 全部 + `neg` / 6 / 3         |         47.5% |         231.9 |          19.0% |

**解读**

- **难度单调性（校准后）**：本表为校准前的首轮大样本（d4 brute 54% 反弹）。校准在
  `family.py` 中为 d4/d5 增加 `min_nodes`（5/7）+ `reject_constant`，消除简单目标后
  重新实验（`/tmp/vica-synth-calib.db`，每难度 200）：**d3 47.5% → d4 23% → d5 11%**
  （brute），**16% → 7.5% → 2%**（random），恢复严格单调。校准细节见下文 §3。
- **穷举基线在 d2 起就不再碾压**：brute 在 d1 保持 100%，d2 降到 65.5%，d3–5 稳定在 ~50%。
- **随机基线在 d3 后几乎失效**：d3 仅 16%，是整条曲线的最低点。

## 3. 规模化后的关键发现

首轮实验（5 实例）观察到的现象，在 200 实例下有**显著更强的证据**：

1. **穷举 vs 随机**：d1 两者接近（100% vs 81%），d2 出现巨大分离（65.5% vs 33.5%），
   d3 达到最大差距（47.5% vs 16%）。d4–5 差距仍保持约 2–3 倍。
2. **brute 成功率不再单调**：d2 从首轮的 100% 降到 65.5%。200 实例暴露了大量
   **过拟合公开测试**的候选——枚举找到的第一个通过全部 public tests 的程序，
   往往不能通过 hidden tests（首轮 d3 已见，规模化后 d2 即大量出现）。
3. **随机基线在 d3 触底**：random 在 d3 只有 16%，说明该难度搜索空间对随机命中
   极其不友好，这是最接近"对通用方法构成挑战"的难度点。

## 4. d4–5 难度校准（2026-08-10）

首轮大样本中 d4 的 brute 反弹（54%）提示 d4 参数偏弱：随着算子池加入 `abs`/`neg`，
简单目标（常数、1–2 节点）占比上升，使枚举/随机更容易命中。校准方案（`family.py`）：

- **`min_nodes`**：d4=5 / d5=7，过滤节点数低于阈值的候选目标。
- **`reject_constant`=True**：拒绝在 16 个随机输入上恒定的目标函数。

校准后重新实验（seed=42，每难度 200，`/tmp/vica-synth-calib.db`）：

| Difficulty | brute (校准前→后) | random (校准前→后) |
|-----------:|------------------:|-------------------:|
| 3 | 47.5% → 47.5% | 16% → 16% |
| 4 | 54.0% → **23.0%** | 24% → **7.5%** |
| 5 | 47.5% → **11.0%** | 19% → **2.0%** |

校准后 d1–d5 brute 成功率 **100% → 65.5% → 47.5% → 23% → 11%**，严格单调递减，
random 同样单调。难度区分度恢复且更陡，为后续 LLM 对比提供干净基线
（见 `docs/reports/synth-v0.1-llm.md`）。

## 5. 验证成本

```text
mean verify time: 16–58 μs（跨难度）
```

- 验证一个候选平均 **16–58μs**，求解从 **<1ms** 到 **800ms** 不等。
- `Solve Cost >> Verify Cost` 成立且在规模化下保持稳定。

## 6. 可复现性

- 相同 `(type, generator_version, seed, difficulty)` 生成相同 payload 与隐藏测试。
- 实验 seed=42，全部 2000 runs 落库 `exp-9925b24b6521`，可通过
  `vica export exp-9925b24b6521` 重新导出（本报告数据文件即由此生成）。
- 隐藏测试在验证时从 `(seed, difficulty)` 确定性重生成，从不分发。

## 7. DoD 对照

| 验收项 | 状态 |
|--------|------|
| ≥1000 实例实验 | ✅ 1000 实例（每难度 200） |
| 全难度 d1–5 覆盖 | ✅ |
| 可复现（seed 42） | ✅ |
| 实验报告 + CSV + JSON | ✅ |
| 验证成本远低于求解成本 | ✅ |
| 难度区分度 | ✅ brute 与 random 在 d2–d5 稳定分离 |

## 8. 结论与下一步

- **SYNTH-v0.1 具备统计显著的难度区分度**：穷举基线与随机基线在 d2–d5 稳定分离，
  满足 Phase 3 DoD 的核心要求。
- **已完成**：
  1. **d4–5 难度校准**（见 §4）：单调难度恢复，d4 brute 54%→23%。
  2. **LLM solver 接入与对比**（见 `docs/reports/synth-v0.1-llm.md`）：`llm-short`
     在 150 实例上 30.7% 优于 brute 26.0%；真实 API 路径（`llm-one-shot` /
     `llm-agent`）已实现，待配置 key 实跑。
- **下一步建议**：
  1. 配置真实 LLM key，跑 `llm-one-shot` / `llm-agent` 三方对比。
  2. 继续 Phase 4 的 Optimization Arena（OPT-v0.1）。