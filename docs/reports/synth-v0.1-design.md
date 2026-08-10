# SYNTH-v0.1 Design Review

**Status**: Design review — 编码前必须通过本评审（TASKS.md Milestone M8）
**目标**: 程序合成任务族，测试 Agentic Problem Solving Efficiency

---

## 1. 任务定义

给定：

```text
- 一个函数签名 f(x) (和一些可选参数说明)
- 10 个公开 (input -> output) 示例
- 资源预算（时间 / 代码大小 / token）
```

要求提交：

```text
- 一个程序（Python 子集 或 受限语言）
- 通过全部公开测试
- 通过全部隐藏测试
- Runtime < 预算
- Code Size < 上限
```

## 2. 任务自动生成（Anti-Memorization）

生成公式：

```text
Challenge =
Gen(type, version, seed, difficulty) -> (signature, public_tests, hidden_tests, budget)
```

生成策略（关键：不能发表过、不能记忆）：

- **原子操作池**: `+ - * mod // ^ min max abs if/else`、循环、递归禁用（v0.1 简化）
- 从函数空间随机采样一个"目标函数"（带树深 / 预算约束），最坏情况保底用
  brute-force 枚举可解到一定难度
- 在公开测试和隐藏测试之间用不同 seed 采样
- 隐藏测试在评测时刻生成，永不下发到求解方

### 候选语言

v0.1 建议 **纯整数表达式语言（受限 DSL）**，不做通用 Python：

```text
expr := term | expr '+' term | expr '-' term
term := factor | term '*' factor | term '%' factor | term '//' factor
factor := int | var | '(' expr ')' | signed_factor
       | min(expr, expr) | max(expr, expr) | abs(expr)
```

好处：

- 验证 = compile + 解释执行，绝对确定性
- 天然避免 `exec`（DSL parser 重写为 AST，解释执行）
- 可以把 sandbox 成本降到极低
- 代码大小 = token 数，可硬性限制

### 函数与公开展示

```text
示例 seed = (version, seed, "public", difficulty)
隐藏 seed = (version, seed, "hidden", difficulty)
```

## 3. Public / Hidden Tests

| 类型 | 数量 | 来源 |
|------|-----|------|
| public | 10 | 固定，随 Challenge 下发 |
| hidden | 30-50 | 评测时生成，永不分发 |

hidden 用例覆盖：边界、负数、0、大数、模 0 异常路径（若 DSL 定义）。

## 4. Deterministic Verifier

```text
candidate_program --parse--> AST --eval--> outputs
outputs compare (public then hidden)
```

- 同一 (challenge, candidate) 永远得到同一判定
- score: 通过隐藏测试的比例（0~1），公开测试全过是 submission 的合法性前提
- **不使用 LLM Judge**

## 5. Sandbox（最高安全优先级）

**禁止在 Arena 主进程直接 `exec(candidate)`**

v0.1 双保险：

1. DSL 解释器：根本不开 eval
2. 若未来引入通用 Python 子集：
   - 独立子进程 + `subprocess.run(timeout=…)`
   - `resource.setrlimit`（CPU / AS memory）
   - 网络禁用（`RLIMIT_NOFILE` + socket? 或容器）
   - 只读最小文件系统（chroot / container）
   - stdout 上限
   - 进程数限制
   - 失败统一记为 `SANDBOX_ERROR` / `TIMEOUT`

## 6. 预算

| 预算项 | v0.1 建议 |
|--------|-----------|
| 求解 wall time | 30s / challenge |
| submission runtime (eval) | 50ms / test 或 1s total |
| code size | 500 tokens |
| 尝试次数（agent 循环） | 5 |
| token 预算 | 每 challenge 上限（如 10k） |

预算本身进入 metadata，作为效率指标的一部分。

## 7. Difficulty 定义

用参数包控制（同 CSP-v0.1 哲学）：

```text
operator_count (可用的 DSL 算子数)
max_depth (目标函数复杂度)
input_width (int range)
hidden_test_count
public_test_count
```

Difficulty 列表（v0.1 草案，待校准）：

| d | 算子 | max_depth | 期望特征 |
|---|-----|-----------|----------|
| 1 | +, - | 2 | 线性，易 |
| 2 | +, -, *, % | 3 | 需乘法 |
| 3 | +, -, *, %, //, min, max | 4 | 条件逻辑 |
| 4 | 全部 + abs | 5 | 非线性 |
| 5 | 全部 + 嵌套 | 6 | 难 |

## 8. Baselines（每条必须同时开发）

| 名字 | 策略 |
|------|------|
| random-program | 随机生成 DSL AST，固定预算 |
| brute-force-enum | 小算子集 / 浅深度，穷举 AST |
| llm-one-shot | LLM 单次输出候选程序 |
| llm-agent | LLM + 本地跑公开测试 + error feedback + 重试（5 次） |
| genetic-programming | 简单 GP，锦标赛选择 |
| hybrid | LLM 生成初始种群 + GP 迭代 |

## 9. 衡量指标

与 CSP-v0.1 相同的整套指标之外，额外：

- public-pass rate, hidden-pass rate, generalization gap（public 通过但 hidden 失败的占比）
- solution/cost, solution/sec
- 尝试次数分布

## 10. 已知风险

| 风险 | 缓解 |
|------|------|
| DSL 太简单，程序可被 brute-force 枚举 | difficulty 5+ 上调搜索空间；记录枚举成本 |
| LLM 记忆训练集上的"经典函数" | 随机生成函数 + 隐藏测试，生成源不公开 |
| DSL 太封闭，测不出"推理" | v0.2 引入循环 + 数组，开放条件 |
| 验证不够快 | DSL AST 解释器是 μs 级，符合规格 |
| sandbox 复杂度失控 | v0.1 仅 DSL，不做通用语言 |

## 11. 验收标准（DoD）

- [ ] 相同 seed 生成相同 challenge（含 hidden tests）
- [ ] DSL parser 确定性
- [ ] verifier 对 (challenge, candidate) 完全确定
- [ ] malformed program 不 crash
- [ ] 5 个 baselines 可运行
- [ ] 至少 1000 实例实验结果 + 报告
- [ ] 恶意 candidate 测试（时间炸弹、无限循环、巨大输出）被 sandbox 拦截
- [ ] pytest 全绿

## 12. 决定与开放问题

待评审确认：

1. 是否保持纯 DSL（v0.1 推荐）还是直接上受限 Python 子集
2. hidden tests 数量与生成方式（seed 明确的伪随机）
3. difficulty presets 的具体参数包
4. 是否把 code size 计入 score（倾向不计，只做软性过滤）