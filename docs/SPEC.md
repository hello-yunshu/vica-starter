# VICA Protocol & Technical Specification v0.1 / v0.2

Status: v0.1 Frozen Core / v0.2 Extensions Under Development  
Scope: Local Arena + CSP-v0.1 / SYNTH-v0.1 / OPT-v0.1 + External Evaluation

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
  "verifier_material_commitment": null,
  "payload": {}
}
```

`verifier_material_commitment`：secret-bound challenge family
（`requires_verifier_secret = True`，当前仅 SYNTH-v0.1）携带完整的 SHA-256
material 承诺（64 hex chars，见 §2.2bis）；普通家族（CSP / OPT）恒为 `null`。

### 2.2 生成约束

普通 challenge family 的 Challenge 必须由下列输入确定：

```text
(type, generator_version, seed, difficulty)
```

相同输入必须生成完全一致的 payload。

verifier-secret-bound family（`requires_verifier_secret = True`）的 Challenge
身份额外绑定 verifier material：

```text
(type, generator_version, seed, difficulty, verifier_material_commitment)
```

即：相同 public seed 但不同 verifier material 应视为**不同的 benchmark
instance**（不同 challenge_id）。该字段在 authoritative 生成路径
（`build_challenge(..., verifier_secret=...)`）由权威方写入，Solver 无法自行决定。

### 2.2bis Verifier-material commitment

```text
verifier_material_commitment =
SHA-256("vica:verifier-material:" + material_version + ":" + verifier_secret)
```

完整 64 hex digest 是协议承诺本身，**不得截断**用于身份绑定；
短 ID（`material_id = commitment[:16]`）仅用于人类 / 数据库显示。

### 2.3 Challenge ID

```text
challenge_id = SHA-256(canonical(identity inputs))
```

identity inputs 与 §2.2 完全一致：

- 普通 family：`(type, generator_version, seed, difficulty, payload)`
- secret-bound family：`(type, generator_version, seed, difficulty, payload,
  verifier_material_commitment)`

`payload` 参与 ID；`verifier_material_commitment = null` 的字段**不**参与普通
family 的 canonical form，因此新增承诺字段不会改变既有 CSP / OPT Challenge ID。

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

**Cost 语义**：`estimated_cost_usd` 允许为 `null`（UNKNOWN / 未测量），
**不等于** 0.0。只有确定知道为 0 时才写 0.0。任何依赖成本的派生指标
（`$/valid`、`valid/$`、`quality/$`）在任一实例 cost 未知时输出 `N/A`
（`None`），不得静默报告为 0。本地计算资源（CPU/GPU）成本尚未折算成美元。

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
Protocol v0.1 canonical serialization 是 **Python-MVP 兼容**实现；跨语言数值
canonicalization（如 JCS / RFC 8785）**尚未冻结**，不要宣称跨语言 Protocol 已最终稳定。

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

    def evaluate(self, challenge: dict, candidate: Any) -> EvaluationResult:
        ...
```

要求：

- `generate` deterministic
- `verify` deterministic
- `score` deterministic
- `evaluate` 是**单一 authoritative evaluation**：一次调用返回
  `(valid, score, error_code)`，`verify_submission` 只调用它一次并复用结果，
  避免对同一 candidate 重复验证/计分。
- 不访问远程 API
- 不依赖 LLM
- 不依赖系统时间

正确性（`valid`/`score`/`error_code`）对同一逻辑输入必须确定不变；
`verify_time_us` 是 telemetry，同输入多次运行可能不同，不属于确定性声明。

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

### 7.1 Solver timeout 语义

`solve()` 因资源受限（墙钟超时、子进程超时、CPU 预算耗尽）未产出 candidate 时，
必须返回 `candidate=None` 并在 `metadata["status"]` 标记 `timeout`；
**不得**把超时当作"模型答错"（`INVALID_SOLUTION` / 计入 success rate 的失败）。

Runner 将 `status == "timeout"` 的 no-candidate 结果记录为 `ErrorCode.TIMEOUT`。

### 7.2 LLM transport error 语义

`llm-*` 系统的 transport 结果稳定映射为以下之一（`metadata["status"]`）：

| status            | 含义                                                    |
|-------------------|---------------------------------------------------------|
| `success`         | HTTP 200 且 body 解析出 candidate                       |
| `timeout`         | 显式超时（客户端 socket 超时或 HTTP 408/429/504）       |
| `transport_error` | 网络层失败（DNS、连接拒绝等）                            |
| `provider_error`  | HTTP 错误状态（非超时族）                                |
| `parse_error`     | HTTP 200 但 body 无法解析出 candidate                    |
| `no_candidate`    | 上述路径均未产出 candidate                              |

- `status` 始终存在；`metadata["last_error"]` 仅在有可诊断错误时存在（否则为 `None`）。
- `timeout` 不作为模型错误：Runner 记 `ErrorCode.TIMEOUT`（同 7.1）。
- `transport_error` / `provider_error` 且无 candidate：Runner 记 `ErrorCode.INTERNAL_ERROR`，
  **不**计入模型的 success-rate 失败。
- `parse_error` / `no_candidate`：Runner 记 `ErrorCode.INVALID_SOLUTION`（模型未给出可验证解）。
- 重试由 solver 明确定义并计数（`metadata["attempts"]`），Runner 不做隐式重试（见 §8）。

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

### Optimization Challenge 质量指标（OPT-v0.1）

对优化类 Challenge，合法解通常 `valid=True`，`success_rate` 无法区分解质量。
评估质量时在实验分析层计算：

```text
raw score / optimal score / regret
regret = optimal_score - candidate_score   （score 越大越好，最优 score 为最大值）
```

OPT-v0.1 的 `opt-dp` 为位掩码（Held-Karp 式）精确基准 O(n·2^n)，作为 optimal
score 参照。不要把 `100% valid` 解释成 `100% solved optimally`。

**Leaderboard 原则**：不把不同 Challenge Family（CSP success / SYNTH success /
OPT mean_score）混成一个单一总分掩盖 trade-off；按 challenge / difficulty / metric
分别展示。

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

### experiment_systems

```text
experiment_id
system_id
type
config_json

PRIMARY KEY (experiment_id, system_id)
```

系统配置是 **experiment-scoped 快照**：每个实验保留自己的 resolved config，
不同实验的相同 `system_id`（如 `llm` 使用不同 model）互不覆盖，历史实验保持
可复现。

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

Schema 版本通过 `PRAGMA user_version` 管理（当前 `2`）。迁移按版本逐步执行，
幂等且可重复打开、不破坏历史数据：

```text
v0  初始发布（origin/main ee61542）的真实旧 schema：
     experiments(id, created_at, config_json, git_commit, vica_version)
     —— 没有 env_json，没有 experiment_systems
v1  ALTER TABLE experiments ADD COLUMN env_json TEXT（不存在才添加）
v2  CREATE TABLE experiment_systems（experiment-scoped 系统配置快照）
```

历史 `experiments` / `runs` 行在迁移中原样保留；迁移后新写入（含
`save_experiment(..., env_json=...)`）必须成功。

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

实现上，Runner 把以上信息写入 `experiments` 表（`env_json` / `git_commit` /
`vica_version` / `config_json`），并把每个 system 的解析后配置写入
`experiment_systems` 表（`config_json`，experiment-scoped 快照）。
**不得保存 API Key / token / credential；不得保存 verifier secret**。

可复现性分级（不要宣称超出实际）：

```text
普通 family（CSP / OPT）复现  强：相同 (type, version, seed, difficulty) => 相同 payload 与 challenge_id
secret-bound family 复现      强：相同 (type, version, seed, difficulty, verifier_material_commitment)
                                   => 相同 payload 与 challenge_id
传统 Solver 复现              较强：确定性算法 + 记录的 config
远程模型实验复现              记录 model/config/provider/date；不保证远程模型未来 bit-identical
```

即使 `temperature=0`，商业 LLM API 也不保证长期 bit-identical，文档/报告必须如实说明。

---

## 14. 安全边界

CSP-v0.1 不执行外部代码，因此风险较低。

SYNTH-v0.1 执行的是**受限纯 DSL 解释器**（无 `exec`、无 `eval`、无循环、无副作用），
不会执行任意的 Python candidate 代码。解释器级守卫（长度/token/嵌套深度/求值步数/
大整数位宽）在 `challenges/synth_v01/family.py` 中实现并映射到 `SANDBOX_ERROR`。

OS 级沙箱（`src/vica/sandbox/`，Milestone M9）是**实验性 OS 资源隔离原型**，
**不是**已硬化、可抵御恶意代码的隔离边界：

- 子进程最小 allowlist 环境（不继承宿主 secrets）、进程组超时清理、CPU/输出/fd 上限：可用。
- 输出是 **bounded streaming**：子进程独立进程组启动，stdout/stderr 通过
  `select` 流式读取；一旦联合输出超过 `max_output_bytes` 立即 kill 整个进程组
  （真正的输出资源上限，不是事后截断；截断只发生在进程已死亡后的残余读取）。
- 内存上限（RLIMIT_AS/DATA）仅 Linux 生效（macOS fork 子进程继承约 400GiB 虚拟足迹）。
- 网络命名空间 / read-only chroot：仅 Linux + root，默认关闭。

因此 TASKS 中 M9 的 network/filesystem/memory/output/syscall 项保持
`[ ]` 或 `[~] experimental`，不标 `[x]`。

禁止在宿主 Python 进程中直接：

```python
exec(candidate)
eval(candidate)
```

---

## 14bis. Verifier Material 与 Solver-Visible Challenge

SYNTH-v0.1 把数据明确分为两类：

### Solver-Visible Challenge（Solver 可看到）

```text
challenge_id / type / generator_version / difficulty / seed(公共) / public payload
verifier_material_commitment（公开的 material 单向承诺）
public examples / budget
```

### Verifier-Only Material（Solver 正常执行路径不能得到）

```text
hidden test seed / hidden test vectors / reference target program / verifier secret
```

隔离机制：hidden tests 由
`HMAC-SHA256(verifier_secret, f"{type}:{version}:hidden:{seed}:{difficulty}")`
派生，reference target 由
`HMAC-SHA256(verifier_secret, f"{type}:{version}:target:{seed}:{difficulty}")`
派生（target 与 hidden 使用不同 tag，domain-separated）。Runner 每次 experiment 解析
一个 verifier_secret（来自 `VICA_VERIFIER_SECRET`，或新生成写入 verifier-private 路径
`<db所在目录>/private/<experiment>.material.json`，权限 0600；默认库 `.vica/vica.db`
对应 `.vica/private/`）。**数据库实验中只保存材料的公开
引用（`verifier_material_commitment` 完整承诺 + `verifier_material_id` 短 ID +
`verifier_material_version`），绝不保存 secret 本身、绝不写入
Challenge、绝不传给任何 Solver、不写入 solver-visible payload**。Solver 只拿到 public
challenge，无法从公开 (seed, difficulty) 重建 target 或 hidden material。

**权威 Verifier 必须先校验 material**：`verify_submission()` 在任意 hidden
evaluation 之前，用传入的 secret 重新派生 commitment 并与
`challenge.verifier_material_commitment` 比对：

```text
secret
    ↓
derive commitment
    ↓
compare challenge.verifier_material_commitment
```

不匹配（或承诺存在但未提供 secret）时：**不执行 hidden tests**，返回
`INTERNAL_ERROR`（内部标记 `verifier_material_mismatch`）。这是 evaluator
configuration failure，**绝不是 Solver 的 `INVALID_SOLUTION`**。
Commitment 是单向承诺（SHA-256 + domain separation），公开后不可反推 secret。

边界测试（`tests/test_synth_generator.py`）：

- solver-visible challenge 不含 verifier secret / hidden tests / target program
- 仅公开 seed 无法重建 hidden tests
- 同 secret + 同 challenge => 相同 hidden material；不同 secret => 不同
- 公开自检通过但权威 verifier（带 secret）拒绝的 overfit candidate

> **注意**：若 Coding Agent 直接工作在仓库根目录（Development Mode），它天然可读
> `src/`。面对真正 adversarial hidden benchmark 时，应把 verifier secret / hidden
> tests / reference solution 移出 Agent 可读 workspace，使用 Evaluation Mode
> （见 README "Security"）。Local Research Arena 的 v0.1 边界是"public challenge
> 不含 verifier material"，不承诺"源码不可读"。

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

---

## 17. v0.2 — Benchmark Research & External Evaluation

> 详细 Bundle 格式见 `docs/protocol/BUNDLE.md`；统计方法见
> `docs/BENCHMARK_METHODOLOGY.md`。本节是协议层增量。

v0.2 在 frozen v0.1 core 之上新增：portable Evaluation Bundle、可插拔
External Solver、可验证的 Result Artifact，以及粗粒度 Benchmark 统计。

### 17.1 Evaluation Bundle

evaluator 生成一批 Challenge，并明确分离 **public**（solver 可见）与
**private**（verifier material）两部分：

```text
<evaluation>/
├── public/
│   ├── manifest.json      # solver-visible metadata + challenges_hash
│   ├── challenges.jsonl   # solver-visible Challenge（每行一个）
│   └── README.md
└── private/
    ├── manifest.json      # verifier-material 引用 + public hash 链接
    └── verifier-material.json  # evaluator secret（0600）
```

public/private 是 **evaluator bundle organization**，不是 OS security isolation。
Coding Agent 只能拿到 `public/`，绝不能拿到整个 evaluation 目录。

### 17.2 版本概念

至少区分：

```text
VICA software version          __version__（如 0.1.0）
Protocol version               vica.protocol 语义版本
Challenge generator version    family.generator_version（改变语义必须升版本）
Bundle format version          BUNDLE_FORMAT_VERSION（独立于 VICA/Protocol/generator）
Verifier material version      verifier/materials.py 的 MATERIAL_VERSION
```

### 17.3 Manifest hash / challenge hash

```text
manifest_hash  = SHA-256(canonical(manifest without "manifest_hash"))
challenges_hash = SHA-256(canonical(challenge_list))
```

使用 `vica.protocol.serialization`；绝不能裸用 `json.dumps`。任何一行
challenge 被改写会在 inspect / verify 时被 `challenges_hash` 检测。

### 17.4 External Solver Protocol（极简，JSON Lines / JSON-in JSON-out）

- **Mode A — File Exchange**（第一优先级）：solver 读 public challenges →
  写 `submissions.jsonl`。编码 Agent / 人类 / 脚本都可参与，无需调 VICA API。
- **Mode B — Command Solver**（第二优先级）：`vica solver run --command ...`，
  VICA 每次把一个 challenge 作为单个 JSON 写入 stdin，solver 把 candidate 作为
  单个 JSON 写回 stdout。

solver 输出格式：

```json
{
  "challenge_id": "...",
  "candidate": {},
  "metadata": {}
}
```

`metadata` 不可信；正确性只依赖 verifier。

### 17.5 Submission Bundle

```text
<submission>/
├── manifest.json
└── submissions.jsonl
```

导入验证语义：

```text
unknown challenge id  -> reject bundle（结构化错误）
missing challenge     -> 记录 NO_SUBMISSION（报告层区分，不等价 INVALID_SOLUTION）
duplicate challenge id -> reject ambiguous input（不静默取最后一个）
malformed candidate    -> 单条失败（INVALID_SCHEMA），不丢弃整批
```

Submission Bundle 是**不可信**输入，设置 max line bytes / max submissions 上限。

### 17.6 Authoritative Verification & Result Bundle

`vica eval verify` 复用 `verify_submission()`（绝无第二套 verifier）：

```text
load public manifest -> load private material -> validate hashes ->
match submission challenge_id -> reconstruct Challenge ->
validate material commitment -> verify_submission() -> record raw result ->
metrics -> result bundle
```

Result Bundle 是可移植第三方可重验 artifact：

```text
manifest.json / evaluation.json / system.json / environment.json /
challenges.jsonl / submissions.jsonl / results.jsonl / metrics.json / report.md
```

Result Bundle 记录 bundder_format_version / evaluation manifest hash / VICA
version / git commit / generator version / commitment / system / raw
submissions / raw results / metrics / environment；**不含** verifier secret /
hidden tests / target / API keys。manifest 携带 bundle_hash / 各文件 sha256。

### 17.7 Reverify（strict）

`vica reverify <result-bundle> --evaluation <eval>` **不重新调用 Solver**，
只重放历史 candidate 走同一权威 verifier：

```text
load historical candidate -> load challenge/public -> load verifier material ->
authoritative verify again -> recompute metrics
```

Strict 模式要求 same generator version / same material commitment / same
challenge id / same verifier semantics，否则拒绝。`verify_time_us` 是 telemetry，
不要求一致；valid / score / error_code 必须一致。

### 17.8 错误分离

```text
Evaluation Failure（evaluator 问题，非 Solver）：
  wrong verifier material / corrupt private bundle / manifest hash mismatch /
  unknown generator version / wrong private material

Solver Outcome（候选质量 / 执行失败）：
  wrong candidate / timeout / parse failure / no candidate
```

报告层必须分开，不能把 evaluator error 算成 Solver failure。

### 17.9 Bundle 端到端流程（v0.2 判定标准）

```text
vica eval prepare ...   -> public challenge bundle
      ↓（交给任意 Coding Agent / LLM / 传统 Solver / 人类 / 脚本）
submission bundle
      ↓
vica eval verify ...    -> result bundle
      ↓（任何有正确 evaluator material 的研究者）
vica reverify ...       -> 得到相同的 valid / score / error semantics
```

这才是 v0.2 是否完成的真正判定标准。
