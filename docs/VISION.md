# VICA Vision

## 1. 项目定义

VICA（Verifiable Intelligence Compute Arena）是一个跨模型、跨算法、跨计算架构的可验证问题解决效率平台。

参与者可以是：

- 商业大模型 API
- 本地开源模型
- AI Agent
- SAT / SMT Solver
- 搜索算法
- 优化算法
- 手写程序
- GPU / CPU 程序
- AI + 传统算法混合系统

VICA 不规定“智能”必须由神经网络产生。

协议只关心：

1. 输入是什么；
2. 输出是否合法；
3. 输出质量如何；
4. 为产生输出消耗了多少资源。

---

## 2. 核心问题

VICA 希望回答：

> 机器智能是否可以用“单位资源下产生多少可验证高质量解”进行测量？

传统 Benchmark 往往测：

- Accuracy
- Pass Rate
- Elo
- Benchmark Score

VICA 希望增加：

- Verified Solutions / Dollar
- Verified Solutions / Second
- Solution Quality / Dollar
- Solution Quality / Joule
- Success Rate at Fixed Budget
- Cost at Fixed Difficulty

---

## 3. 核心假设

项目需要实验验证，而不是预设以下假设一定成立。

### H1：存在 Hard-to-Solve / Easy-to-Verify 的任务族

即：

```text
Solve Cost >> Verify Cost
```

### H2：不同计算系统在这些任务上存在稳定效率差异

例如同样 $1 预算：

```text
System A -> 800 valid solutions
System B -> 300 valid solutions
System C -> 40 valid solutions
```

### H3：难度可以连续调节

目标是形成：

```text
Difficulty -> Solve Cost
Difficulty -> Success Rate
Difficulty -> Latency
```

稳定曲线。

### H4：更好的推理、搜索或规划能力能转化为更高求解效率

而不是所有任务最终都退化成纯 brute force。

---

## 4. 设计原则

### 模型中立

不绑定 GPT、Claude、Gemini、Qwen、Llama 或任何单一模型。

### 算法中立

传统 Solver 如果更强，就应该赢。

### 确定性验证

核心正确性判定不能依赖 LLM Judge。

### 可复现

Challenge 由：

```text
type + generator_version + seed + difficulty
```

唯一确定。

### 成本透明

Benchmark 模式尽可能记录：

- input_tokens
- output_tokens
- API cost
- wall time
- CPU time
- GPU time
- energy
- attempts
- success rate

### 主动攻击自己的 Benchmark

每加入一种 Challenge，同时开发：

- baseline
- specialized solver
- attack strategy

如果存在明显捷径，就记录、调整或淘汰该 Challenge。

---

## 5. 项目不是什么

VICA 当前不是：

- 区块链项目
- 加密资产项目
- Token 项目
- 模型训练平台
- 聊天机器人排行榜
- 单一厂商 Benchmark

---

## 6. 长期愿景

如果核心假设成立，VICA 可以演化为：

### Intelligence Efficiency Benchmark

比较不同系统在单位资源下的真实问题解决能力。

### Agent Benchmark

评测：

```text
Plan -> Act -> Observe -> Retry -> Optimize
```

的完整 Agent 闭环，而非单次回答。

### Verifiable Compute Research Platform

研究如何让未知执行方提交结果，而验证方无需重复全部计算。

### Hybrid Intelligence Arena

研究 AI 与传统算法的最优组合。

### Distributed Problem Solving Platform

未来在验证机制成熟后，再研究远程执行、任务市场、声誉和调度。

---

## 7. 项目核心资产

长期最有价值的不是模型 wrapper，而是：

1. Challenge Library
2. Deterministic Verifier Library
3. Benchmark Dataset
4. Efficiency Metrics
5. Solver / Agent Ecosystem
6. Challenge Attack Knowledge Base

---

## 8. 一句话愿景

> VICA 试图建立一种新的机器智能测量方式：给系统一个未知问题、有限预算和有限时间，观察它能产生多少客观可验证的有效结果。
