# 长桥 LongPort 模拟盘失败场景冒烟

这份文档的目标：

- 给 `longport-paper` 提供一套更贴近真实操作员的失败场景冒烟操作手册
- 优先验证“失败后怎么观察、怎么留证、怎么恢复”，而不是继续扩新平台能力
- 明确哪些场景今天适合手工模拟盘复现，哪些场景更适合交给自动化回归证明

这份文档刻意不做两件事：

- 不把仓库推成新的券商模拟器
- 不为了硬造拒单、部分成交或 `pending-cancel` 去补一套额外测试框架

## 1. 什么时候值得跑

当你已经满足下面这些条件时，这份操作手册才有价值：

- `LONGPORT_ACCESS_TOKEN_TEST` 已经配置好
- `qexec config --broker longport-paper`
- `qexec preflight --broker longport-paper`
- `qexec account --broker longport-paper`
- `qexec quote AAPL --broker longport-paper`

而且这些基础检查都能稳定通过。

如果连这里都不稳，先不要做失败场景冒烟；先把模拟盘就绪性跑顺。

## 2. 先准备一个固定证据目录

建议先准备一组固定输出路径，别每次临时乱放：

```bash
mkdir -p outputs/evidence
mkdir -p outputs/targets
```

推荐约定：

- 基线顺利路径证据：  
  `outputs/evidence/longport-paper-baseline.json`
- 本地阻断 / 操作员复核证据：  
  `outputs/evidence/longport-paper-blocked.json`

如果你需要长期保留，也可以按日期细分子目录，但没必要再为此加一层系统。

## 3. 第一层：手工可复现的操作员失败场景冒烟

这一层只包含今天就能低成本反复跑的场景。

### 场景 A：基线操作员流程

先确认基础模拟盘流程是稳定的，不然失败场景冒烟没有对照组。

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker longport-paper \
  --execute \
  --cleanup-open-orders \
  --evidence-output outputs/evidence/longport-paper-baseline.json
```

这一步至少要确认：

- `config -> account -> quote -> rebalance -> orders -> reconcile -> exceptions` 能跑完
- 如果拿到了已跟踪订单引用，`order` 也能跑
- `cancel-all` 能把模拟盘 open order 收尾
- 证据 JSON 里 `success=true`
- 证据 JSON 里 `failed_step=null`

如果这一步都不稳，不要继续补更复杂的失败场景冒烟。

### 场景 B：手动紧急停单 / 本地阻断

这个场景的目标不是让工装故意崩掉，而是验证：

- 本地紧急停单会不会按预期拦截变更类操作
- 操作员能不能从输出、异常队列和本地状态里看清楚“为什么没下单”

先准备一个最小 `targets` 文件，例如：

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

然后用紧急停单跑一次：

```bash
QEXEC_KILL_SWITCH=1 qexec rebalance \
  outputs/targets/longport-paper-failure-smoke.json \
  --broker longport-paper \
  --execute
```

这里要注意一件事：

- 这更像“本地阻断的操作员结果”
- 不一定会让 CLI 返回非零退出码
- 重点是确认本地风控 / 紧急停单阻断被记录清楚，而不是强行把它当成子进程硬失败

随后立刻看：

```bash
qexec exceptions --broker longport-paper --status blocked
qexec orders --broker longport-paper --status failure
qexec state-doctor --broker longport-paper
```

你要确认的不是“命令有没有变红”，而是：

- 阻断原因是否可解释
- `exceptions` 能否看到本地 `BLOCKED`
- 状态文件和异常视图能否对上

这类场景很像真实操作员会遇到的本地拦截，比硬造一个伪券商拒单更有价值。

### 场景 C：操作员清理 / 刷新

如果基线或阻断场景之后你怀疑本地状态有残留，不要直接删文件，先走运维链路：

```bash
qexec reconcile --broker longport-paper
qexec exceptions --broker longport-paper
qexec state-doctor --broker longport-paper
```

如果 `doctor` 提示的是安全可修的本地问题，再考虑：

```bash
qexec state-repair --broker longport-paper --clear-kill-switch
qexec state-repair --broker longport-paper --dedupe-fills --drop-orphan-fills
```

这一步的重点是验证：

- 操作员是不是能先看事实，再修本地状态
- 状态维护命令是否足够克制，而不是动不动就手工删 `outputs/state/*.json`

### 场景 D：机会型记录部分成交 / `pending-cancel`

LongPort 模拟盘并不保证你能稳定、低成本、可重复地手工造出：

- `PARTIALLY_FILLED`
- `PENDING_CANCEL`
- 迟到成交

所以这类场景不要为了“演示一次”去造轮子。

但如果模拟盘账户自然撞上了这些状态，就按下面流程留证，不要临场发挥：

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

## 4. 第二层：更适合自动化回归证明的失败契约

下面这些失败场景当前已经有自动化覆盖，但不值得为了手工模拟盘重复性去硬造：

- `rebalance` 步骤失败后，证据里是否保留部分执行过程
- `orders` / `order` / `reconcile` / `exceptions` / `cancel-all` 中途失败后，后续步骤是否停止
- `rebalance` 后没有已跟踪订单引用时，`order` 是否会被跳过
- `reconcile` 的 `get_order` / `list_fills` 异常告警是否能保留
- 部分成交 / `pending-cancel` / 迟到成交的恢复契约

当前建议直接跑聚焦回归：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_smoke_operator_harness.py -q
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_execution_foundation.py -q
```

这两组测试当前已经锁住了：

- `success`
- `failed_step`
- `failure_category`
- `next_step_hint`
- `skipped_steps`

以及执行生命周期的关键失败模式。

这里的意思不是“手工冒烟不重要”，而是：

- 模拟盘手工冒烟更适合验证操作员流程和证据留存
- 结构化失败契约更适合交给自动化测试反复兜底

## 5. 证据怎么看

`smoke_operator_harness.py --evidence-output ...` 当前至少会保留这些字段：

- `success`
- `failed_step`
- `failure_category`
- `next_step_hint`
- `skipped_steps`
- `operator_outcome_status`
- `operator_outcome_source`
- `operator_outcome_message`
- `operator_outcome_category`
- `operator_next_step_hint`
- `state_path`
- `latest_tracked_order_ref`
- `steps`
