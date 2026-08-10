# VICA 项目说明与实施规划

## Verifiable Intelligence Compute Arena

**可验证智能计算竞技场**

---

# 1. 项目定位

VICA 是一个研究和评测不同智能计算系统在**可验证复杂任务**上的效率、成本与能力差异的开放实验平台。

项目关注的核心问题不是某个具体模型的回答质量，而是：

> 是否可以设计一类“求解困难、验证廉价、难度可控、结果客观”的计算任务，并以此衡量不同智能系统的实际问题解决能力？

参与系统可以包括：

- 商业大模型 API
- 本地开源模型
- AI Agent
- 搜索算法
- SAT / SMT Solver
- 优化算法
- 传统程序
- GPU / CPU 计算程序
- AI 与传统算法组成的混合系统

VICA 不限定参与者必须使用 AI。

所有系统都在统一任务、统一验证器和统一计量标准下竞争。

---

# 2. 项目核心思想

传统 AI Benchmark 通常关注：

```text
Accuracy
Pass Rate
Benchmark Score
```

VICA 希望增加另一组维度：

```text
Solution Quality
───────────────
Cost

Solution Quality
───────────────
Time

Valid Solutions
───────────────
Compute
```

换句话说，VICA 不只是问：

> 谁能解决问题？

而是进一步问：

> 谁能以更低成本、更短时间和更少资源，稳定产生可验证的高质量解？

最终希望形成一种：

**Intelligence Efficiency Benchmark**

即：

**智能效率评测体系。**

---

# 3. 核心研究问题

项目首先研究六个问题。

## Q1

是否存在这样的任务：

```text
求解成本 >> 验证成本
```

也就是：

**Hard to Solve, Easy to Verify**

---

## Q2

不同模型之间是否会表现出稳定的效率差异？

例如：

```text
Model A
Model B
Model C
```

在相同预算下产生不同数量的有效解。

---

## Q3

商业模型、本地模型与传统算法之间的效率关系是什么？

例如：

```text
LLM
vs
Search
vs
Solver
vs
Hybrid Agent
```

---

## Q4

更高模型能力是否会稳定转化为更高：

```text
Valid Solutions / Dollar
```

或者：

```text
Valid Solutions / Second
```

---

## Q5

AI 与传统算法的混合架构是否会明显优于单一模型？

例如：

```text
LLM
 ↓
任务分析
 ↓
生成搜索策略
 ↓
Solver
 ↓
候选答案
 ↓
LLM 修正
```

---

## Q6

能否构建一套与具体模型厂商无关的：

**Verifiable Intelligence Protocol**

即：

**可验证智能计算协议。**

---

# 4. 项目原则

VICA 从第一天开始遵循几个原则。

## 4.1 模型中立

协议不关心：

> 你使用了什么模型？

只关心：

> 你提交的结果是否合法，以及产生结果消耗了多少资源。

---

## 4.2 算法中立

允许：

```text
GPT
Claude
Gemini
Llama
Qwen
DeepSeek
SAT Solver
Genetic Algorithm
Search
Custom Algorithm
Hybrid Agent
```

参加同一任务。

---

## 4.3 客观验证

所有核心任务必须拥有：

**Deterministic Verifier**

即：

```text
Candidate
    ↓
Verifier
    ↓
Valid / Invalid
```

禁止使用：

```text
LLM Judge
```

作为核心正确性判断标准。

---

## 4.4 成本透明

平台应该尽可能记录：

```text
Token
API Cost
Latency
CPU Time
GPU Time
Energy
Attempts
Success Rate
```

---

## 4.5 可复现

任何 Challenge 都应该能够通过：

```text
Generator Version
+
Seed
+
Difficulty
```

重新生成。

---

# 5. 第一阶段不做什么

VICA v0.x 阶段不考虑：

- Token
- 区块链
- 钱包
- 加密资产
- 共识网络
- 金融激励
- DAO
- staking
- P2P 网络

第一阶段只研究：

> **可验证智能任务本身是否具有稳定、可重复、有意义的能力区分度。**

---

# 6. 系统架构

```text
                  Challenge Generator
                          │
                          ▼
                     Challenge
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
   AI System        Traditional       Hybrid Agent
                       Solver
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
                          ▼
                     Candidate
                          │
                          ▼
               Deterministic Verifier
                          │
                    ┌─────┴─────┐
                    │           │
                  Valid       Invalid
                    │
                    ▼
                  Score
                    │
                    ▼
                Benchmark
                    │
                    ▼
                Leaderboard
```

---

# 7. 核心模块

VICA 最小系统由五部分组成。

## 7.1 Challenge Generator

负责生成任务。

输入：

```text
seed
difficulty
challenge_type
generator_version
```

输出：

```text
Challenge
```

必须保证：

- 随机性
- 可复现
- 难度可调
- 不依赖人工逐题编写
- 可以持续生成新实例

---

# 8. Candidate

参与系统提交：

```json
{
  "challenge_id": "...",
  "candidate": {},
  "metadata": {}
}
```

Benchmark 模式下 metadata 可以包含：

```text
model
provider
strategy
input_tokens
output_tokens
latency
api_cost
hardware
cpu_time
gpu_time
attempts
```

---

# 9. Verifier

Verifier 是整个项目最核心的基础设施之一。

必须满足：

```text
Deterministic
Fast
Reproducible
Model-independent
```

即相同：

```text
Challenge + Candidate
```

永远得到相同验证结果。

目标：

```text
Verification Cost << Solution Cost
```

例如：

```text
求解：1 秒

验证：1 毫秒
```

或者：

```text
求解：$0.01

验证：$0.000001
```

---

# 10. Score

部分任务只有：

```text
Valid / Invalid
```

但更值得研究的是：

```text
score(candidate)
```

例如：

```text
72
83
91
97
```

这样可以直接比较不同系统的解质量。

---

# 11. Difficulty

任务必须具有连续的难度控制机制。

例如通过调整：

```text
变量数量
约束数量
搜索空间
隐藏测试数量
目标分数
时间限制
程序长度限制
问题规模
```

实现：

```text
Difficulty 1
Difficulty 2
...
Difficulty N
```

目标是最终获得一条稳定的：

```text
Difficulty → Cost
```

曲线。

---

# 12. 第一类 Challenge：Constraint Satisfaction

第一版建议从约束满足问题开始。

例如：

```text
变量：

A B C D E F G H ...

取值范围：

0 - 31
```

随机生成约束：

```text
A + B = 19
C XOR D = 12
E < F
G != H
I * J mod 31 = 8
K + L + M = 40
...
```

系统输出：

```json
{
  "A": 7,
  "B": 12,
  "C": 5
}
```

Verifier 逐条检查约束。

---

# 13. Constraint Challenge 的作用

它并不一定是 VICA 最终最重要的任务。

它主要用于验证：

```text
Protocol
Generator
Verifier
Difficulty
Benchmark Runner
Metrics
```

整个系统能否正常工作。

与此同时也可以获得第一个有价值结果：

> AI 模型在标准约束问题上，相比传统 Solver 到底有没有效率优势？

如果答案是没有：

这同样是重要实验结果。

---

# 14. 第二类 Challenge：Program Synthesis

Program Synthesis 很可能是 VICA 最值得重点研究的方向之一。

任务示例：

```text
给定函数签名

以及：

10 个公开 Input → Output 示例
```

要求生成一个程序：

```text
f(x)
```

并满足：

```text
通过所有公开测试

通过所有隐藏测试

Runtime < 50 ms

Code Size < 500 Bytes
```

---

# 15. Program Synthesis 为什么重要

生成程序可能需要：

```text
理解
推理
假设
尝试
运行
反馈
修改
```

但验证只需要：

```text
compile
 ↓
sandbox
 ↓
run tests
 ↓
pass / fail
```

因此天然接近：

```text
Solve Cost >> Verify Cost
```

并且 LLM 本身天然具备代码生成能力。

---

# 16. Program Synthesis Agent

一个典型参与系统可以是：

```text
Challenge
    ↓
LLM 分析规律
    ↓
生成 Candidate Program
    ↓
本地运行公开 Tests
    ↓
失败
    ↓
Error Feedback
    ↓
LLM 修正
    ↓
再次测试
    ↓
Submit
```

此时实际上测试的是：

**Agentic Problem Solving Efficiency**

而不仅仅是单次模型输出。

---

# 17. 第三类 Challenge：Optimization

这是另一个非常重要的方向。

例如：

- Scheduling
- Routing
- Packing
- Graph Optimization
- Planning
- Resource Allocation
- Assignment
- Knapsack Variants

系统提交一个合法方案。

Verifier 计算：

```text
score(candidate)
```

例如：

```text
score = 92.3
```

任务目标：

```text
score >= threshold
```

---

# 18. Optimization 的优势

Difficulty 可以天然定义成：

```text
Difficulty 1:
score >= 70

Difficulty 2:
score >= 80

Difficulty 3:
score >= 90

Difficulty 4:
score >= 95
```

因此模型能力越强：

可能越容易发现高质量方案。

---

# 19. 第四类 Challenge：Search & Discovery

未来还可以研究：

**Search Challenge**

给定巨大的组合空间。

要求发现满足特定规则的对象。

例如：

```text
Graph
Sequence
Program
Expression
Schedule
Structure
Configuration
```

验证 Candidate 很容易。

发现 Candidate 很困难。

这种任务天然适合测试：

```text
Search Intelligence
```

---

# 20. Challenge 设计标准

一个优秀的 VICA Challenge 应尽可能满足：

```text
Hard to Solve
+
Easy to Verify
+
Difficulty Adjustable
+
Infinite Instances
+
Low Precomputation Value
+
Objective Scoring
+
Multiple Solution Strategies
```

最好还满足：

```text
Better Reasoning
→
Better Efficiency
```

---

# 21. 一个重要原则

VICA 不应该尝试设计：

> “只有 LLM 能解决的问题。”

这是错误方向。

真正合理的目标是：

> **允许任何算法参与，并观察什么系统最终效率最高。**

如果某一天传统算法发现新方法：

它理应登上排行榜第一。

这是系统设计的一部分，而不是漏洞。

---

# 22. 核心 Benchmark 指标

## Valid Rate

```text
valid_candidates
────────────────
total_candidates
```

---

## Success Rate

```text
solved_challenges
─────────────────
total_challenges
```

---

## Cost per Solution

```text
total_cost
──────────────
valid_solutions
```

记作：

```text
$/Solution
```

---

# 23. Solutions per Dollar

```text
Valid Solutions
───────────────
Dollar
```

这是 VICA 最重要的指标之一。

可以简称：

**SPD**

---

# 24. Solutions per Second

```text
Valid Solutions
───────────────
Second
```

简称：

**SPS**

衡量时间效率。

---

# 25. Token Efficiency

对于模型：

```text
Solutions
────────────
1M Tokens
```

可以比较不同模型的 token 利用效率。

---

# 26. Energy Efficiency

针对本地 GPU：

```text
Solutions
─────────
kWh
```

可以比较：

```text
API
vs
Local GPU
vs
CPU Solver
```

的真实资源效率。

---

# 27. Quality / Cost

对于 Optimization Challenge：

```text
Average Solution Score
──────────────────────
Dollar
```

用于衡量：

**单位成本产生的解质量。**

---

# 28. Intelligence Efficiency Index

项目未来可以建立一个综合指标：

**IEI**

Intelligence Efficiency Index

例如综合：

```text
Success Rate
Score
Latency
Cost
Difficulty
```

形成：

```text
IEI =
Verified Problem-Solving Performance
────────────────────────────────────
Resource Consumption
```

具体公式在获得真实实验数据之后再设计。

不要过早固定。

---

# 29. Arena 排行榜

最终可以展示：

```text
VICA ARENA

System          Success   Cost      $/Solution
------------------------------------------------
System A        74%       $10.20    $0.0056
System B        69%       $5.10     $0.0036
Local 8B        45%       $2.80     $0.0012
SAT Solver      93%       $0.30     $0.00004
Hybrid Agent    97%       $1.20     $0.0007
```

这里最有价值的不是：

> 谁最聪明？

而是：

> 在什么任务上，什么系统的整体效率最高？

---

# 30. 多维排行榜

不能只有一个总榜。

建议建立：

```text
Best Accuracy

Best Cost Efficiency

Best Latency

Best Local Model

Best API Model

Best Traditional Algorithm

Best Hybrid System
```

这样可以观察不同技术路线之间的关系。

---

# 31. Challenge-Specific Ranking

例如：

```text
CSP Leaderboard

Program Synthesis Leaderboard

Optimization Leaderboard

Planning Leaderboard
```

不同系统可能在不同任务上占优。

这本身就是重要研究结果。

---

# 32. 软件架构

推荐：

```text
vica/
│
├── protocol/
│   ├── challenge.py
│   ├── candidate.py
│   ├── result.py
│   └── serialization.py
│
├── challenges/
│   ├── base.py
│   ├── csp/
│   ├── synthesis/
│   ├── optimization/
│   └── search/
│
├── verifier/
│   ├── base.py
│   ├── verifier.py
│   └── sandbox.py
│
├── systems/
│   ├── base.py
│   ├── random/
│   ├── solver/
│   ├── openai/
│   ├── anthropic/
│   ├── gemini/
│   ├── local/
│   └── hybrid/
│
├── arena/
│   ├── runner.py
│   ├── benchmark.py
│   ├── metrics.py
│   └── leaderboard.py
│
├── server/
│   ├── api.py
│   ├── challenge_server.py
│   └── submission_server.py
│
├── storage/
│
├── web/
│
├── tests/
│
└── README.md
```

---

# 33. Participant System Interface

所有系统使用相同接口：

```python
class SolverSystem:

    def solve(self, challenge):
        ...

    def metadata(self):
        ...
```

例如：

```text
OpenAIAdapter

ClaudeAdapter

LocalModelAdapter

SATAdapter

RandomSearchAdapter

HybridAgentAdapter
```

---

# 34. Challenge Interface

统一接口：

```python
class Challenge:

    def generate(seed, difficulty):
        ...

    def verify(candidate):
        ...

    def score(candidate):
        ...

    def serialize():
        ...
```

这样以后可以不断增加新的 Challenge Family。

---

# 35. Protocol v0.1

最小 API：

```text
GET /challenge
```

返回：

```json
{
  "id": "...",
  "type": "csp-v0.1",
  "generator_version": "0.1",
  "seed": "...",
  "difficulty": 10,
  "payload": {}
}
```

参与系统求解后：

```text
POST /candidate
```

提交：

```json
{
  "challenge_id": "...",
  "system_id": "...",
  "candidate": {},
  "metadata": {}
}
```

服务器：

```text
Load Challenge
       ↓
Verify
       ↓
Score
       ↓
Measure
       ↓
Store Result
```

---

# 36. Canonical Serialization

协议必须从第一版开始定义：

**Canonical Serialization**

即：

同一个 Challenge 或 Candidate：

无论在哪台机器上，都生成完全相同的字节表示。

例如：

```text
canonical(candidate)
```

这一点对：

```text
Hash
Caching
Deduplication
Reproducibility
Future Distributed Verification
```

都非常重要。

---

# 37. Challenge Generator

Generator 应满足：

```text
Challenge =
Generate(
    challenge_type,
    generator_version,
    seed,
    difficulty
)
```

例如：

```text
CSP-v0.1
```

未来可以升级：

```text
CSP-v0.2

SYNTH-v0.1

OPT-v0.1

SEARCH-v0.1
```

---

# 38. Anti-Benchmark-Gaming

公开评测平台很容易被针对。

因此后续必须考虑：

## 隐藏实例

公开：

```text
Generator specification
```

但评测 seed 在测试时才产生。

---

## 隐藏测试

Program Synthesis 中：

```text
Public Tests
+
Hidden Tests
```

---

## Dynamic Challenge

Challenge 实例不断变化。

不能单纯记忆答案。

---

## Evaluation Budget

例如：

```text
60 Seconds

$0.10 Budget

10,000 Tokens
```

保证公平比较。

---

# 39. Program Sandbox

Program Synthesis 涉及执行不可信代码。

必须默认：

```text
Candidate Code = Untrusted
```

因此必须：

```text
Network Disabled

Filesystem Restricted

CPU Limit

Memory Limit

Runtime Limit

Process Limit

Syscall Restriction
```

绝不能直接在服务端：

```text
exec(candidate)
```

---

# 40. Phase 0：协议定义

目标：

完成 VICA Protocol v0.1。

包括：

```text
Challenge

Candidate

Result

Score

Difficulty

Serialization
```

成功标准：

协议完全 deterministic。

---

# 41. Phase 1：Local Arena

实现：

```text
CSP Challenge

Random Baseline

Traditional Solver

1 个 Local Model

Benchmark Runner
```

至少运行：

```text
1,000 Challenges
```

并获得第一份数据。

---

# 42. Phase 2：Model Arena

接入多个模型系统。

例如：

```text
Commercial API A

Commercial API B

Commercial API C

Small Local Model

Large Local Model
```

统一记录：

```text
Tokens

Cost

Latency

Attempts

Success Rate
```

核心输出：

```text
$/Solution
```

---

# 43. Phase 3：Program Synthesis Arena

这是项目真正进入研究阶段的开始。

开发：

```text
SYNTH-v0.1
```

测试：

```text
LLM

Code Agent

Search

Genetic Programming

Hybrid Agent
```

比较：

```text
Success
Cost
Latency
Generalization
```

---

# 44. Phase 4：Optimization Arena

实现：

```text
OPT-v0.1
```

引入：

```text
solution score
```

开始研究：

```text
Quality / Cost
```

而不是单纯正确率。

---

# 45. Phase 5：Challenge Research

这一阶段的主要工作不是开发平台功能。

而是：

**寻找优质 Challenge Families。**

每开发一种 Challenge，都同时开发：

```text
Baseline Algorithm

Attack Algorithm

Specialized Solver
```

主动尝试击败自己的 Benchmark。

---

# 46. Challenge 淘汰机制

如果一个 Challenge：

```text
LLM 需要 $0.01
```

但专用算法：

```text
0.1 ms
```

解决。

那么：

这类 Challenge 对衡量通用智能效率的价值可能有限。

应该：

```text
淘汰

调整

或者明确归类
```

---

# 47. Phase 6：Public Arena

当 Challenge 与 Benchmark 成熟后：

公开：

```text
Challenge API

Submission API

SDK

Leaderboard

Dataset
```

允许外部开发者提交自己的：

```text
Model

Agent

Solver

Algorithm
```

---

# 48. Phase 7：Distributed Compute Research

只有在前面真正发现稳定的：

```text
Hard-to-Solve
Easy-to-Verify
```

任务之后，才研究：

```text
Distributed Workers

Task Marketplace

Remote Verification

Reputation

Compute Scheduling
```

这一层属于后续平台化能力。

---

# 49. MVP

第一版 MVP 只需要：

```text
1 个 Challenge Generator

1 个 Deterministic Verifier

1 个 Random Baseline

1 个 Solver Baseline

1 个 AI Adapter

1 个 Benchmark Runner

1 个 Result Database

1 个简单 Leaderboard
```

完全够用。

---

# 50. 第一版建议技术栈

Backend：

```text
Python 3.12+

FastAPI

Pydantic
```

Database：

```text
SQLite
```

后续：

```text
PostgreSQL
```

Benchmark：

```text
Python
```

前端初期可以非常简单。

真正重要的是：

```text
Challenge

Verifier

Metrics
```

不是 UI。

---

# 51. MVP 成功标准

第一阶段不以用户数作为成功标准。

而是研究结果。

### 成功条件 A

至少一种 Challenge 能稳定区分不同系统。

---

### 成功条件 B

存在明显：

```text
Solve Cost >> Verify Cost
```

---

### 成功条件 C

Difficulty 与 Solve Cost 之间存在稳定关系。

---

### 成功条件 D

不同系统之间存在可重复的：

```text
Cost Efficiency
```

差异。

---

### 成功条件 E

AI + Algorithm Hybrid 至少在部分任务上表现出明显竞争力。

---

# 52. 项目风险

最大风险不是工程实现。

而是：

## Risk 1

所有任务最终都被专用 Solver 极低成本解决。

---

## Risk 2

任务只有 AI 能判断结果。

导致无法廉价验证。

---

## Risk 3

Benchmark 最终只是测某种固定技巧。

而不是较通用的问题解决能力。

---

## Risk 4

模型可以通过记忆训练数据而非真实推理获得优势。

---

## Risk 5

Challenge Difficulty 无法稳定控制。

---

## Risk 6

API 价格差异掩盖模型能力差异。

因此必须同时报告：

```text
Raw Capability

Cost Efficiency
```

两个维度。

---

# 53. 研究价值

如果项目成功，它可以产生几个不同方向的价值。

## AI Benchmark

测量：

```text
真实问题解决效率
```

而不是单纯知识问答正确率。

---

## Agent Benchmark

特别适合测试：

```text
Plan

Execute

Observe

Retry

Optimize
```

这类 Agent 能力。

---

## Algorithm Benchmark

把 AI 和传统算法放进同一个竞技环境。

---

## Compute Economics

研究：

```text
Intelligence / Dollar
```

以及：

```text
Intelligence / Energy
```

---

## Verifiable AI

研究：

> 如何在不信任计算执行方的情况下，低成本验证其最终结果？

---

## Distributed Intelligence

未来可以探索：

```text
Distributed Problem Solving
```

而不仅仅是分布式计算。

---

# 54. 项目可能形成的核心资产

如果项目长期发展，真正有价值的资产不是某个模型 Wrapper。

而是以下几项：

### Challenge Library

高质量、自动生成、难度可调的任务族。

---

### Verifier Library

安全、高性能、确定性的验证框架。

---

### Benchmark Dataset

不同系统在大量 Challenge 上的历史表现。

---

### Efficiency Metrics

一套成熟的智能效率评估体系。

---

### Solver Ecosystem

大量：

```text
Models

Agents

Algorithms

Hybrid Systems
```

在统一环境下竞争。

---

# 55. 最核心的研究目标

项目最终希望研究一个目前还没有很好定义的问题：

> **机器智能是否可以用“单位资源下产生多少可验证高质量解”来衡量？**

也就是：

```text
Verified Intelligence Output
────────────────────────────
Resource Consumption
```

资源可以分别定义成：

```text
Dollar

Time

Tokens

GPU Time

Energy
```

---

# 56. 项目长期定位

如果实验成功，VICA 不应该仅仅被定位为：

**一个 LLM Benchmark。**

更准确的定位应该是：

> **一个跨模型、跨算法、跨计算架构的可验证问题解决效率平台。**

其参与者可以是：

```text
AI Model

Agent

Traditional Solver

Human-designed Algorithm

Hybrid Intelligence System
```

统一通过：

```text
Challenge

Candidate

Verifier

Score

Cost
```

进行比较。

---

# 57. 推荐开发顺序

严格建议：

```text
Protocol v0.1
        ↓
Canonical Serialization
        ↓
Challenge Interface
        ↓
CSP-v0.1
        ↓
Verifier
        ↓
Random Baseline
        ↓
Solver Baseline
        ↓
AI Adapter
        ↓
Benchmark Runner
        ↓
1,000-instance Experiment
        ↓
数据分析
        ↓
SYNTH-v0.1
```

不要先做复杂 Web UI。

不要先做分布式架构。

不要先做商业化。

---

# 58. 第一阶段最终应该得到什么

第一阶段真正有价值的结果应该是一组实验数据，例如：

```text
Challenge: CSP-v0.1
Difficulty: 8

System          Success   Avg Time   Cost       Score
-------------------------------------------------------
Random          0.2%      10.0 s     $0         -
Solver          100%      0.03 s     $0.00001   -
Small Model     38%       2.1 s      $0.0008    -
Large Model     71%       4.3 s      $0.006     -
Hybrid Agent    96%       0.8 s      $0.0004    -
```

然后进一步得到：

```text
Difficulty → Success

Difficulty → Cost

Difficulty → Latency
```

曲线。

这些才是项目下一步决策依据。

---

# 59. Go / Pivot / No-Go

完成首轮实验之后，不预设结果。

## GO

如果发现：

```text
任务具有区分度

验证成本极低

Difficulty 可控

不同系统存在稳定差异
```

继续扩大 Challenge Families。

---

## PIVOT

如果传统 Solver 全面领先：

转向研究：

**Hybrid Intelligence**

即：

```text
AI + Traditional Algorithm
```

如何产生最高问题解决效率。

这个方向本身非常值得做。

---

## NO-GO

如果长期找不到：

```text
Hard-to-Solve

Easy-to-Verify
```

的问题类型，或者评测结果高度随机、不可复现，则停止向复杂基础设施扩展。

---

# 60. 项目愿景

VICA 最终希望建立的不是某个模型排行榜。

而是一种新的机器智能观察方式。

传统 Benchmark 更多回答：

> 模型知道多少？

VICA 更希望回答：

> 给机器一个未知问题、有限时间和有限预算，它能够产生多少经过客观验证的有效结果？

因此项目最终关注的是：

**Verifiable Problem-Solving Efficiency**

即：

**可验证问题解决效率。**

长期可以进一步研究：

```text
Verified Solutions / Dollar

Verified Solutions / Second

Solution Quality / Dollar

Solution Quality / Joule
```

从而建立一套：

**面向真实计算经济性的智能评测体系。**

---

# 61. 一句话项目定义

**VICA 是一个让 AI 模型、Agent、传统算法和混合计算系统，在自动生成、客观可验证的复杂任务上竞争问题解决效率的开放实验平台。**

---

# 62. 当前实施重点

现阶段只集中投入三个核心模块：

```text
Challenge

Verifier

Benchmark
```

其中最重要的是：

**Challenge Design。**

整个项目最终是否有价值，主要取决于能否发现这样的问题族：

```text
求解困难

验证容易

难度连续可调

实例可以无限生成

结果客观

不存在长期固定捷径

不同智能系统存在稳定效率差异
```

如果这一点成立，其他平台能力都可以随后构建。