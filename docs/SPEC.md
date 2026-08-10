# VICA Protocol & Technical Specification v0.1

Status: Draft  
Scope: Local Arena + CSP-v0.1

---

## 1. 目标

Protocol v0.1 只定义完成首轮实验所需的最小对象：

- Challenge
- Candidate
- Result
- Difficulty
- Score
- Canonical Serialization
- Solver System Interface
- Verifier Interface

v0.1 不定义：

- 分布式共识
- 金融奖励
- 身份系统
- 链
- P2P
- 长期信誉

---

## 2. Challenge

### 2.1 逻辑结构

```json
{
  "id": "string",
  "type": "csp-v0.1",
  "generator_version": "0.1.0",
  "seed": "hex-or-uuid",
  "difficulty": 1,
  "payload": {}
}
```

### 2.2 生成约束

Challenge 必须由下列输入确定：

```text
(type, generator_version, seed, difficulty)
```

相同输入必须生成完全一致的 payload。

### 2.3 Challenge ID

建议：

```text
challenge_id =
BLAKE3(canonical(challenge_without_id))
```

若 MVP 暂不引入 BLAKE3 依赖，可先使用 SHA-256。

---

## 3. Candidate

```json
{
  "challenge_id": "string",
  "system_id": "string",
  "candidate": {},
  "metadata": {}
}
```

### 3.1 metadata

metadata 仅作为 Benchmark 数据，不参与正确性判定。

建议字段：

```json
{
  "provider": "local|openai|anthropic|...",
  "model": "string",
  "strategy": "string",
  "input_tokens": 0,
  "output_tokens": 0,
  "estimated_cost_usd": 0.0,
  "wall_time_ms": 0,
  "cpu_time_ms": 0,
  "gpu_time_ms": 0,
  "attempts": 1
}
```

metadata 默认是不可信自报数据。

本地 Arena 中优先由 Runner 自动采集可测字段。

---

## 4. Result

```json
{
  "challenge_id": "string",
  "system_id": "string",
  "valid": true,
  "score": 1.0,
  "verify_time_us": 150,
  "error_code": null
}
```

错误码建议：

```text
INVALID_SCHEMA
WRONG_CHALLENGE
INVALID_SOLUTION
TIMEOUT
SANDBOX_ERROR
INTERNAL_ERROR
```

---

## 5. Canonical Serialization

所有需要哈希、缓存、去重或复现的对象必须使用统一 canonical representation。

v0.1 规则：

1. UTF-8
2. JSON
3. object key 按字典序排序
4. 禁止 NaN / Infinity
5. 不输出多余空格
6. 数字格式必须稳定
7. 字符串使用 JSON 标准转义

Python MVP 可使用：

```python
json.dumps(
    obj,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

注意：

正式跨语言协议发布前，需要对浮点数序列化做更严格约束。

---

## 6. Challenge Interface

```python
from typing import Protocol, Any

class ChallengeFamily(Protocol):
    type_name: str
    generator_version: str

    def generate(self, seed: str, difficulty: int) -> dict:
        ...

    def verify(self, challenge: dict, candidate: Any) -> bool:
        ...

    def score(self, challenge: dict, candidate: Any) -> float:
        ...
```

要求：

- `generate` deterministic
- `verify` deterministic
- `score` deterministic
- 不访问远程 API
- 不依赖 LLM
- 不依赖系统时间

---

## 7. Solver System Interface

```python
class SolverSystem(Protocol):
    system_id: str

    def solve(self, challenge: dict) -> "SolveOutput":
        ...
```

```python
@dataclass
class SolveOutput:
    candidate: object
    metadata: dict
```

所有系统：

- Random
- SAT / SMT
- Local Model
- Commercial API
- Hybrid Agent

使用相同接口。

---

## 8. Benchmark Runner

Runner 负责：

1. 生成 challenge
2. 启动计时
3. 调用 solver
4. 收集 candidate
5. 调用 verifier
6. 记录 verify time
7. 保存 raw result
8. 聚合 metrics

Runner 不负责：

- 修改 solver 输出
- 用 LLM 二次判断
- 隐式重试，除非该 strategy 明确定义重试

---

## 9. CSP-v0.1

### 9.1 目标

CSP-v0.1 主要用于验证整个框架。

它不是最终 Benchmark。

### 9.2 变量

Difficulty 映射建议：

```text
d=1  -> 8 variables
d=2  -> 12 variables
d=3  -> 16 variables
...
```

每个变量整数取值：

```text
0 <= Xi <= max_value
```

### 9.3 约束类型

首版建议只采用安全、简单、确定性的整数约束：

- equality
- inequality
- addition
- modular addition
- xor
- all-different subsets
- bounded linear relation

示例：

```text
A + B = 17
C XOR D = 13
E < F
G != H
(I + J + K) mod 31 = 9
```

### 9.4 确保有解

Generator 不应该随机生成后再祈祷有解。

建议：

1. 先随机生成一个隐藏 solution；
2. 再从该 solution 反向构造约束；
3. 逐步增加约束；
4. 可选：使用 solver 检查唯一性或解空间大小。

这样至少保证存在一个有效解。

### 9.5 Candidate 格式

```json
{
  "A": 4,
  "B": 13,
  "C": 7
}
```

Verifier 检查：

- 所需变量全部存在
- 不允许多余变量（v0.1 建议严格）
- 类型为整数
- 范围合法
- 每条约束满足

---

## 10. Difficulty

v0.1 不追求一个“完美”难度公式。

先定义多个可调参数：

```text
variable_count
domain_size
constraint_count
constraint_density
constraint_mix
```

外部 difficulty level 只是预设参数包。

例如：

```python
DIFFICULTY_PRESETS = {
    1: {...},
    2: {...},
    3: {...},
}
```

后续根据实验数据重新标定。

---

## 11. Metrics

首轮必须输出：

### Per Run

- challenge_id
- challenge_type
- difficulty
- system_id
- valid
- score
- solve_wall_time_ms
- verify_time_us
- attempts
- input_tokens
- output_tokens
- estimated_cost_usd

### Aggregate

- success_rate
- mean_latency
- p50_latency
- p95_latency
- mean_cost_per_challenge
- cost_per_valid_solution
- valid_solutions_per_dollar
- valid_solutions_per_second

对于本地系统，可额外输出：

- CPU time
- GPU time
- energy estimate

---

## 12. 数据存储

MVP 推荐 SQLite。

最小表：

### challenges

```text
id
type
generator_version
seed
difficulty
payload_json
created_at
```

### systems

```text
id
type
config_json
```

### runs

```text
id
challenge_id
system_id
candidate_json
valid
score
solve_wall_time_ms
verify_time_us
metadata_json
created_at
```

---

## 13. Reproducibility

每个 Benchmark run 必须保存：

- git commit hash
- VICA version
- challenge generator version
- system config
- random seed
- environment metadata

目标：

别人可以重新运行同一 experiment。

---

## 14. 安全边界

CSP-v0.1 不执行外部代码，因此风险较低。

进入 Program Synthesis 后必须新增独立 sandbox 规格。

禁止在宿主 Python 进程中直接：

```python
exec(candidate)
eval(candidate)
```

---

## 15. API 草案

### GET /challenge

响应：

```json
{
  "id": "...",
  "type": "csp-v0.1",
  "generator_version": "0.1.0",
  "seed": "...",
  "difficulty": 3,
  "payload": {}
}
```

### POST /candidate

请求：

```json
{
  "challenge_id": "...",
  "system_id": "...",
  "candidate": {},
  "metadata": {}
}
```

响应：

```json
{
  "valid": true,
  "score": 1.0,
  "verify_time_us": 127
}
```

Public Arena 前，Server 不是 MVP 必需项。

---

## 16. v0.1 验收条件

Protocol v0.1 完成必须满足：

- [ ] 相同 seed 生成相同 Challenge
- [ ] canonical serialization 单元测试通过
- [ ] verifier 100% deterministic
- [ ] malformed candidate 不导致 crash
- [ ] Random baseline 可运行
- [ ] Solver baseline 可运行
- [ ] Benchmark runner 可批量跑 1,000 instances
- [ ] 所有 run 可落库
- [ ] 可以导出 CSV / JSON
- [ ] pytest 全绿
