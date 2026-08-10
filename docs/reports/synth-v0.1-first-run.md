# SYNTH-v0.1 First Run Report

**Experiment**: `exp-baf77c8aa95d`
**Date**: 2026-08-10
**VICA version**: 0.1.0
**Challenge**: `synth-v0.1` (generator_version `0.1.0`)
**Difficulties**: 1, 2, 3
**Instances**: 5 per difficulty (30 runs total)
**Systems**: `synth-random`, `synth-brute`
**Experiment seed**: 42
**Raw data**: `synth-v0.1-first-run-runs.json`, `synth-v0.1-first-run-metrics.csv`
**Database**: `/tmp/vica-synth-exp.db`

> 本报告是 SYNTH-v0.1 挑战族的首次小规模验收实验。目的是验证程序合成挑战族的
> 生成 / 验证 / 基线闭环是否工作，并初步观察难度区分度——尤其是设计文档中提出的
> Risk 1（SYNTH-v0.1 能否被穷举求解）。

---

## 1. 汇总表

| System        | d | Success | Mean ms | p50 ms | p95 ms | Mean Verify μs |
|---------------|--:|--------:|--------:|-------:|-------:|---------------:|
| synth-brute   | 1 | 100.0%  |     0.2 |    0.1 |    0.7 |           26.8 |
| synth-brute   | 2 | 100.0%  |    37.9 |    0.2 |  120.4 |           51.8 |
| synth-brute   | 3 |  60.0%  |    26.6 |    0.2 |  131.8 |           28.2 |
| synth-random  | 1 |  80.0%  |     1.0 |    0.6 |    2.8 |           28.0 |
| synth-random  | 2 |  20.0%  |     1.8 |    2.0 |    2.2 |           15.2 |
| synth-random  | 3 |  20.0%  |     2.4 |    2.9 |    3.0 |           11.2 |

```text
difficulty=1..3, instances=5 each, seed=42
```

## 2. Difficulty 曲线

| Difficulty | Operators                 | Depth | Vars | brute Success | brute Mean ms | random Success |
|-----------:|---------------------------|------:|-----:|--------------:|--------------:|---------------:|
| 1 | `+ -`                      |     2 |    1 |        100.0% |           0.2 |          80.0% |
| 2 | `+ - * %`                  |     3 |    1 |        100.0% |          37.9 |          20.0% |
| 3 | `+ - * % // min max`       |     4 |    2 |         60.0% |          26.6 |          20.0% |

**解读**

- 难度单调可调：运算符集合从 2 个扩展到 7 个，表达式深度从 2 增至 4，
  输入变量从 1 个增至 2 个，搜索空间指数级增长。
- 两个基线系统的成功率均随难度递减：
  - synth-brute: 100% → 100% → 60%
  - synth-random: 80% → 20% → 20%
- **这是 SYNTH-v0.1 的第一条 `Difficulty → Success Rate` 曲线。**

## 3. 系统间对比

| 指标               | synth-brute | synth-random |
|--------------------|------------|--------------|
| d=1 成功率          | 100%       | 80%          |
| d=2 成功率          | 100%       | 20%          |
| d=3 成功率          | 60%        | 20%          |
| 平均求解时间 (d=2)  | 37.9ms     | 1.8ms        |
| 失败时是否耗尽预算  | 是         | 是 (500 次)  |

**关键发现**

1. **穷举枚举在 d=1-2 完全碾压随机搜索**：brute-force 在 d=2 仍保持 100% 成功率，
   而 random 降至 20%。这是因为 d=2 的目标程序节点数较少（深度 3），枚举空间
   仍可覆盖。
2. **d=3 是 brute-force 的转折点**：5 个实例中 2 个失败。
   - `42:3:2`：brute 在 0.9ms 内找到候选但验证失败（`INVALID_SOLUTION`）——
     候选程序通过了全部公开测试但未通过隐藏测试，属于**过拟合公开测试**。
   - `42:3:4`：brute 耗时 132ms 后仍未找到解，搜索预算耗尽。
3. **随机搜索在 d=2 以上几乎失效**：当 random 失败时，总是耗尽全部 500 次尝试，
   说明搜索空间已远超随机命中概率。

## 4. 设计文档 Risk 验证

设计文档 (`docs/reports/synth-v0.1-design.md`) 提出 Risk 1：
"SYNTH-v0.1 能否被穷举求解？"

| 难度 | 能否被穷举 | 证据 |
|------|-----------|------|
| d=1  | 完全可以  | 5/5，mean 0.2ms |
| d=2  | 完全可以  | 5/5，mean 37.9ms，但 p95 已达 120ms |
| d=3  | 部分可以  | 3/5，出现预算耗尽和过拟合 |
| d=4-5 | 待验证   | 预计穷举失效（深度 5-6，运算符 7 个） |

**结论**：SYNTH-v0.1 在 d=1-2 可被穷举，d=3 开始出现区分度，d=4-5 预计
对传统方法构成真正的挑战。这验证了设计文档的预期，且符合 AGENTS.md
不变量 #7（"specialized solver outperforming AI is a valid research result"）。

## 5. 验证成本

```text
mean verify time: 10–52 μs (跨难度)
verify is 100% deterministic (regenerates hidden tests from seed+difficulty)
```

验证一个候选程序平均耗时 **10–52μs**（含 DSL 解析 + 迭代式求值 + 全部 40 个隐藏测试）。
求解耗时从 **0.02ms** 到 **132ms** 不等。SYNTH-v0.1 满足 `Solve Cost >> Verify Cost`。

## 6. 可复现性验证

- 相同 `(type, generator_version, seed, difficulty)` 生成相同 payload
  （`test_synth_generator.py` 覆盖）。
- challenge id = SHA-256 of canonical(challenge without id)，跨进程稳定。
- 所有 run 落库到 SQLite，可通过 `vica export <experiment-id>` 重新导出。
- 隐藏测试在验证时从 `(seed, difficulty)` 确定性重生成，从不分发。

## 7. 基础设施验收

| 验收项 | 状态 |
|--------|------|
| SYNTH-v0.1 注册到 registry | ✅ |
| 生成器确定性 | ✅ `test_generate_is_deterministic` |
| 验证器确定性 + 沙箱守卫 | ✅ `test_synth_verifier.py`（深度/步数/位长守卫） |
| DSL 解析/打印 round-trip | ✅ `test_synth_generator.py` |
| 迭代式求值无栈溢出 | ✅ 对抗性宽表达式测试通过 |
| synth-random 基线可运行 | ✅ |
| synth-brute 基线可运行 | ✅ |
| Runner 端到端 (生成→求解→验证→落库) | ✅ 30 runs |
| 导出 CSV / JSON | ✅ `vica export` |
| pytest 全绿 | ✅ 129 passed, ruff clean, mypy clean |

## 8. 结论与下一步

**本实验回答的问题**

1. SYNTH-v0.1 闭环 ✅ —— 生成 / 验证 / 基线 / Runner 全链路工作正常。
2. 确定性 ✅ —— 完全满足，隐藏测试从 seed 重生成。
3. 验证成本 ✅ —— 极低（μs 级），远低于求解成本。
4. 难度控制 ✅ —— 曲线单调，运算符/深度/变量数三维可调。
5. 区分度 ✅ —— d=3 已出现 brute-force 与 random 的分离，d=4-5 预计更显著。

**待扩展**

- 扩大实验规模（d=1-5, 100+ instances）以获得统计显著性。
- 接入 LLM solver，观察 LLM 在程序合成任务上与穷举基线的对比。
- 校准 d=4-5 的难度参数，确保对传统方法和 AI 都有挑战性。
