# 长桥 LongPort 模拟盘 failure smoke

这份文档的目标：

- 给 `longport-paper` 提供一套更贴近真实 operator 的 failure smoke playbook
- 优先验证“失败后怎么观察、怎么留证、怎么恢复”，而不是继续扩新平台能力
- 明确哪些场景今天适合手工 paper 复现，哪些场景更适合交给自动化回归证明

这份文档刻意不做两件事：

- 不把仓库推成新的 broker simulator
- 不为了强造 reject / partial-fill / pending-cancel 去补一套额外测试框架

## 1. 什么时候值得跑

当你已经满足下面这些条件时，这份 playbook 才有价值：

- `LONGPORT_ACCESS_TOKEN_TEST` 已经配置好
- `qexec config --broker longport-paper`
- `qexec preflight --broker longport-paper`
- `qexec account --broker longport-paper`
- `qexec quote AAPL --broker longport-paper`

这些基础检查都能稳定通过

如果连这里都不稳，先不要做 failure smoke；先把 paper readiness 跑顺。

## 2. 先准备一个固定证据目录

建议先准备一组固定输出路径，别每次临时乱放：

```bash
mkdir -p outputs/evidence
mkdir -p outputs/targets
```

推荐约定：

- baseline happy path evidence：
  `outputs/evidence/longport-paper-baseline.json`
- local blocked / operator review evidence：
  `outputs/evidence/longport-paper-blocked.json`

如果你需要长期保留，也可以按日期细分子目录，但没必要再为此加一层系统。

## 3. 第一层：手工可复现的 operator failure smoke

这一层只包含今天就能低成本反复跑的场景。

### 场景 A：baseline operator workflow

先确认基础 paper workflow 是稳定的，不然 failure smoke 没有对照组。

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker longport-paper \
  --execute \
  --cleanup-open-orders \
  --evidence-output outputs/evidence/longport-paper-baseline.json
```

这一步至少要确认：

- `config -> account -> quote -> rebalance -> orders -> reconcile -> exceptions` 能跑完
- 如果拿到了 tracked order ref，`order` 也能跑
- `cancel-all` 能把 paper open order 收尾
- evidence JSON 里 `success=true`
- evidence JSON 里 `failed_step=null`

如果这一步都不稳，不要继续补更花的 failure smoke。

### 场景 B：manual kill switch / local block

这个场景的目标不是让 harness 故意崩，而是验证：

- 本地 kill switch 会不会按预期拦截 mutation
- operator 能不能从输出、异常队列和本地 state 看清楚“为什么没下单”

先准备一个最小 targets 文件，例如：

```json
{
  "schema_version": 2,
  "asof": "paper-failure-smoke",
  "source": "operator-smoke",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_quantity": 1,
      "notes": "manual kill switch smoke"
    }
  ]
}
```

保存为：

```bash
outputs/targets/longport-paper-failure-smoke.json
```

然后用 kill switch 跑一次：

```bash
QEXEC_KILL_SWITCH=1 qexec rebalance \
  outputs/targets/longport-paper-failure-smoke.json \
  --broker longport-paper \
  --execute
```

这里要注意一件事：

- 这更像“BLOCKED operator outcome”
- 不一定会让 CLI 返回非零退出码
- 重点是确认本地 risk / kill-switch block 被记录清楚，而不是强行把它当成 subprocess hard failure

随后立刻看：

```bash
qexec exceptions --broker longport-paper --status blocked
qexec orders --broker longport-paper --status failure
qexec state-doctor --broker longport-paper
```

你要确认的不是“命令红没红”，而是：

- block 原因是否可解释
- `exceptions` 能否看到本地 `BLOCKED`
- state 文件和异常视图能否对上

这类场景非常像真实 operator 会遇到的本地拦截，比硬造一个伪 broker reject 值钱得多。

### 场景 C：operator cleanup / refresh

如果 baseline 或 blocked smoke 之后你怀疑本地 state 有残留，不要直接删文件，先走运维链路：

```bash
qexec reconcile --broker longport-paper
qexec exceptions --broker longport-paper
qexec state-doctor --broker longport-paper
```

如果 doctor 提示的是安全可修的本地问题，再考虑：

```bash
qexec state-repair --broker longport-paper --clear-kill-switch
qexec state-repair --broker longport-paper --dedupe-fills --drop-orphan-fills
```

这一步的重点是验证：

- operator 是不是能先看事实，再修本地 state
- state maintenance 命令是否足够克制，而不是动不动就手工删 `outputs/state/*.json`

### 场景 D：opportunistic partial-fill / pending-cancel capture

LongPort paper 不保证你能稳定、便宜、可重复地手工造出：

- `PARTIALLY_FILLED`
- `PENDING_CANCEL`
- late fill

所以这类场景不要为了“演示一次”去造轮子。

但如果 paper 账户自然撞上了这些状态，就按下面流程留证，不要临场 improvisation：

```bash
qexec orders --broker longport-paper --status open --symbol AAPL
qexec exceptions --broker longport-paper --status partially_filled,pending_cancel --symbol AAPL
qexec order <tracked-order-ref> --broker longport-paper
qexec reconcile --broker longport-paper
```

然后按状态做最保守处置：

- `PARTIALLY_FILLED`：
  `cancel-rest` / `resume-remaining` / `accept-partial`
- `PENDING_CANCEL`：
  先 `reconcile`，不要急着 `retry` / `reprice`

对应命令：

```bash
qexec cancel-rest <tracked-order-ref> --broker longport-paper
qexec resume-remaining <tracked-order-ref> --broker longport-paper
qexec accept-partial <tracked-order-ref> --broker longport-paper
```

## 4. 第二层：更适合由自动化回归证明的 failure contract

下面这些 failure-mode 当前已经有自动化覆盖，但不值得为了手工 paper 重复性去强造：

- `rebalance` 步骤失败后，evidence 是否保留 partial transcript
- `orders` / `order` / `reconcile` / `exceptions` / `cancel-all` 中途失败后，后续步骤是否停止
- `rebalance` 后没有 tracked order ref 时，`order` 是否会被跳过
- reconcile 的 `get_order` / `list_fills` 异常 warning 是否能保留
- partial-fill / pending-cancel / late-fill 的恢复契约

当前建议直接跑聚焦回归：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_smoke_operator_harness.py -q
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_execution_foundation.py -q
```

这两组测试现在已经锁住了：

- `success`
- `failed_step`
- `failure_category`
- `next_step_hint`
- `skipped_steps`

以及 execution lifecycle 的关键 failure-mode。

这里的意思不是“手工 smoke 不重要”，而是：

- paper 手工 smoke 更适合验证 operator workflow 和证据留存
- 结构化失败契约更适合交给自动化测试反复兜底

## 5. evidence 怎么看

`smoke_operator_harness.py --evidence-output ...` 现在至少会保留这些字段：

- `success`
- `failed_step`
- `failure_category`
- `next_step_hint`
- `skipped_steps`
- `state_path`
- `latest_tracked_order_ref`
- `steps`

如果 evidence 里看到：

- `success=true`
  说明 workflow 跑完了，不代表每一笔 order 都是 broker success
- `success=false`
  说明 harness 在某个步骤边界停下来了
- `failed_step=reconcile`
  先看这一步 stderr，再看 `next_step_hint`
- `skipped_steps`
  表示后续哪些步骤没有继续跑，以及原因

它现在的定位是 operator evidence，不是单纯 stdout 转存。

## 6. 一次 smoke 至少要留下什么

无论是 baseline 还是 failure smoke，至少保留：

- `targets.json`
- `outputs/evidence/*.json`
- `outputs/orders/*.jsonl`
- `outputs/state/*.json`
- 一段人工备注：
  包括运行时间、symbol、最后一个 tracked ref、最终状态、是否发生本地 block、有没有人工 cleanup

## 7. 什么时候可以停

如果下面这些都已经稳定，你就已经把 `longport-paper` 用到了一个很合适的程度：

- baseline operator workflow 稳定
- local block / kill-switch smoke 可解释
- `exceptions` / `order` / `reconcile` / `state-doctor` 能支持排障
- 关键 failure contract 已经有自动化回归
- 你知道自然出现 partial-fill / pending-cancel 时该怎么处理

到这一步就够像一个成熟的 execution 学习项目了。

再往下如果是为了“更漂亮地造 synthetic broker failure”，大概率已经开始偏离这个仓库最值钱的边界。
