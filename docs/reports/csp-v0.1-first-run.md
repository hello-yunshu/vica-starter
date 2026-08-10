# CSP-v0.1 First Run Report

**Experiment**: `exp-0d158dde4bcc`
**Date**: 2026-08-10
**VICA version**: 0.1.0
**Challenge**: `csp-v0.1` (generator_version `0.1.0`)
**Difficulties**: 1, 2, 3, 4, 5
**Instances**: 200 per difficulty (1,000 challenges total)
**Systems**: `random`, `z3`
**Experiment seed**: 42
**Raw data**: `csp-v0.1-first-run-runs.json`, `csp-v0.1-first-run-metrics.csv`
**Database**: `vica.db`

> 本报告是 VICA 平台基础设施的第一次验收实验。它的目的不是证明某个系统强，
> 而是验证 Protocol / Generator / Verifier / Runner / Storage / Metrics 的完整闭环
> 是否能工作，并产出第一份可复现数据。

---

## 1. 汇总表

| System  | Success | Mean ms | p50 ms | p95 ms | Mean Verify μs | $/sol |
|---------|--------:|--------:|-------:|-------:|---------------:|------:|
| random  |   1.1%  |    7.4  |   7.3  |   10.7 |           0.1  | —     |
| z3      |  95.0%  |  579.8  |  80.3  | 4748.1 |           6.8  | ~0    |

```text
difficulty=1..5, instances=200 each, seed=42
```

## 2. Difficulty 曲线

| Difficulty | Variables | Constraints | z3 Success | z3 Mean ms | z3 p50 ms | random Success |
|-----------:|----------:|------------:|-----------:|-----------:|----------:|---------------:|
| 1 |  8 |  7 | 100% |  55.7 |   6.0 |  5.5% |
| 2 | 12 | 10 | 99.5% | 296.8 |  21.7 |  0.0% |
| 3 | 16 | 13 | 95.5% | 543.1 |  57.5 |  0.0% |
| 4 | 20 | 16 | 91.5% | 914.0 | 178.5 |  0.0% |
| 5 | 24 | 19 | 88.5% | 1089.5 | 285.1 |  0.0% |

**解读**

- 难度连续可调且单调：变量和约束数量随 difficulty 递增，z3 的求解时间随难度
  单调上升（mean 55.7ms → 1089.5ms，p50 6.0ms → 285.1ms）。
- 这是第一条 `Difficulty → Solve Cost` 曲线。
- 随机基线的成功率为零（除 d=1 的 5.5% 噪声），把"必须真求解"的下限钉死了。

## 3. Solve Cost vs Verify Cost

对 961 个有效提交：

```text
median solve/verify ratio ≈ 5,241x
mean   solve/verify ratio ≈ 23,763x
max    solve/verify ratio ≈ 344,106x
```

验证一个候选平均耗时约 **6.8μs**，而求解耗时从 **6ms** 到 **秒级** 不等。
CSP-v0.1 满足 `Solve Cost >> Verify Cost`。

## 4. 可复现性验证

- 相同 `(type, generator_version, seed, difficulty)` 生成相同 payload
  （`test_csp_generator.py` 覆盖）。
- challenge id = SHA-256 of canonical(challenge without id)，跨进程稳定。
- 所有 run 落库到 SQLite，可通过 `vica export <experiment-id>` 重新导出。
- 同一实验可重复运行（`--seed 42`）。

## 5. 基础设施验收（SPEC v0.1 验收条件）

| 验收项 | 状态 |
|--------|------|
| 相同 seed 生成相同 Challenge | ✅ `test_generate_is_deterministic` |
| canonical serialization 单元测试 | ✅ `test_serialization.py`（golden vectors、unicode、NaN 拒绝） |
| verifier 100% deterministic | ✅ 重复验证 50 次结果一致 |
| malformed candidate 不 crash | ✅ diff-fuzz 覆盖 |
| Random baseline 可运行 | ✅ |
| Solver baseline 可运行 | ✅ z3 |
| Runner 批量 1,000 instances | ✅ 本次实验 1,000 challenges |
| 所有 run 落库 | ✅ 2000 runs |
| 导出 CSV / JSON | ✅ `vica export` |
| pytest 全绿 | ✅ 80 passed, ruff clean, mypy clean |

## 6. 结论与下一步

**本实验回答的问题**

1. 平台闭环 ✅ 工作正常 —— Protocol 到 Leaderboard 全链路跑通。
2. 确定性 ✅ 完全满足。
3. 验证成本 ✅ 极低（μs 级）。
4. 难度控制 ✅ 曲线单调，可调。
5. 区分度 ⚠️ CSP 本身是"Solver 碾压"型任务（z3 95% vs random 1.1%），对
   "谁更智能"几乎没有区分力 —— 这正是项目文档预期的结果。

**对 Go / Pivot / No-Go 的初步判断**

CSP-v0.1 属于基础设施任务，不应作为最终 Benchmark。它验证了平台可用，
但对"智能效率"的区分度有限（传统 solver 占绝对优势），符合 ROADMAP 的预期
（"CSP 很可能被 Solver 碾压，这本身就是结果"）。

下一步按路线图进入：

- `docs/reports/synth-design.md`（SYNTH-v0.1 设计评审）后实现 SYNTH-v0.1；
- 同时保持 CSP 作为快速冒烟级任务。

**保留的观察**

- z3 在 d=5 时成功率为 88.5%，说明难度参数开始逼近 solver 的计算极限
  （5s timeout），这对 future difficulty calibration 是个有用的锚点。
- random 在 d=1 的 5.5% 成功率为"碰巧解出小实例"的天然基线，可用于
  校验难度下限是否有意义。