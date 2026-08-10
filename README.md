# VICA

**Verifiable Intelligence Compute Arena**  
可验证智能计算竞技场

VICA 是一个让 AI 模型、Agent、传统算法和混合计算系统，在自动生成、客观可验证的复杂任务上竞争问题解决效率的开放实验平台。

## 核心目标

VICA 研究的不是“哪个模型最会聊天”，而是：

> 在未知任务、有限时间和有限预算下，哪个计算系统能以更低成本产生更多经过确定性验证的高质量解？

核心关注：

- Hard to Solve, Easy to Verify
- Difficulty 可调
- Challenge 可无限生成
- Verifier 确定性、低成本
- 模型 / 算法 / Agent 中立
- 统一测量成本、延迟、成功率和解质量

## 当前阶段

当前只做实验平台，不做：

- 区块链
- Token
- 钱包
- 共识
- 金融激励
- P2P 网络

当前核心资产只有三个：

1. Challenge
2. Verifier
3. Benchmark Data

## 当前进展

已完成（v0.1.0）：

- CSV/JSON 导出、指标报表、鉴权默认关闭 —— 已实现

## 首个里程碑

完成 `CSP-v0.1`：

- 自动生成约束满足任务
- Deterministic Verifier
- Random baseline
- Traditional solver baseline
- 一个模型适配器
- Benchmark runner
- 1,000 个实例的首轮实验
- 首轮实验结果：`docs/reports/csp-v0.1-first-run.md`（Random 1.1% vs Z3 95.0%）

## 仓库结构

```text
vica/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── .gitignore
├── docs/
│   ├── VISION.md
│   ├── SPEC.md
│   ├── ROADMAP.md
│   ├── TASKS.md
│   └── PROMPTS.md
├── src/vica/
│   ├── protocol/
│   ├── challenges/
│   ├── verifier/
│   ├── systems/
│   ├── arena/
│   └── server/
└── tests/
```

## 推荐开发顺序

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
Model Adapter
  ↓
Benchmark Runner
  ↓
1,000-instance Experiment
  ↓
SYNTH-v0.1
```

## 本地初始化

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## 文档

- [项目愿景](docs/VISION.md)
- [协议与技术规格](docs/SPEC.md)
- [路线图](docs/ROADMAP.md)
- [实施任务清单](docs/TASKS.md)
- [Coding Agent 提示词](docs/PROMPTS.md)
