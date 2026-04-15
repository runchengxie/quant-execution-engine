# CLI 大全

## 命令入口

推荐入口：

```bash
qexec
```

兼容入口：

```bash
stockq
```

开发环境也可以直接执行：

```bash
PYTHONPATH=src python -m quant_execution_engine
```

## 子命令

### `config`

显示当前 broker backend、risk gate、kill switch 和相关凭证摘要。

```bash
qexec config
qexec config --broker alpaca-paper
```

### `preflight`

运行不改 broker 状态的 readiness 检查。

```bash
qexec preflight
qexec preflight AAPL MSFT
qexec preflight --broker alpaca-paper
qexec preflight --broker longport-paper
```

当前会检查：

- capability matrix
- live execution guard
- manual kill switch
- local state kill switch
- account resolution
- account snapshot
- quotes / depth / volume reachability

### `account`

查看账户概览。

```bash
qexec account
qexec account --format json
qexec account --funds
qexec account --positions
qexec account --broker alpaca-paper
qexec account --account main
```

### `quote`

查询实时行情。

```bash
qexec quote AAPL 700.HK
qexec quote AAPL --broker alpaca-paper
```

### `orders`

查看本地 execution state 里跟踪的 broker orders。

```bash
qexec orders
qexec orders --status open
qexec orders --status failure
qexec orders --symbol AAPL
qexec orders --status open --symbol AAPL.US
qexec orders --broker alpaca-paper
```

### `exceptions`

查看本地 execution state 中的异常队列，包含本地 `BLOCKED` / `FAILED` 和需要人工关注的 broker 状态。

```bash
qexec exceptions
qexec exceptions --status failure
qexec exceptions --status partially_filled,pending_cancel
qexec exceptions --symbol MSFT
qexec exceptions --broker alpaca-paper
```

### `order`

查看单笔 tracked order 的本地执行详情。

```bash
qexec order 1234567890
qexec order child_abcd1234_1
qexec order client-order-id --broker alpaca-paper
```

输出会合并展示 intent / parent / child / broker / fill 信息，以及最近一次 manual resolution、normalized diagnostic 和 action hint。

### `reconcile`

手动触发一次 broker reconcile，并把刷新后的状态写回 `outputs/state/*.json`。

```bash
qexec reconcile
qexec reconcile --broker alpaca-paper
qexec reconcile --account main
```

summary 当前会展示：

- tracked order 变更数量
- 每笔订单的状态 / 成交量变化
- 新补录的 fill
- 规范化 warning code 和 next-step hint

### `cancel`

按 tracked order ref 发起撤单。

```bash
qexec cancel 1234567890
qexec cancel child_abcd1234_1
qexec cancel client-order-id --broker alpaca-paper
```

### `cancel-rest`

撤掉一笔部分成交订单的剩余未成交部分。

```bash
qexec cancel-rest 1234567890
```

只支持：

- 已有部分成交
- 剩余量仍大于 0
- broker 侧当前仍是 open 状态

### `cancel-all`

撤销本地 execution state 中仍然 open 的全部 tracked broker orders。

```bash
qexec cancel-all
qexec cancel-all --broker alpaca-paper
```

### `retry`

重试一笔零成交的失败 / 撤销 tracked order。

```bash
qexec retry 1234567890
qexec retry client-order-id --broker alpaca-paper
```

### `resume-remaining`

在部分成交后，为剩余量提交新的 child attempt。

```bash
qexec resume-remaining 1234567890
```

只支持：

- 已有部分成交且仍有剩余量
- 原 broker order 已不再 open
- 剩余量当前是整数股
- 尚未被 `accept-partial` 本地关闭

### `accept-partial`

接受部分成交结果，并在本地关闭剩余量期待。

```bash
qexec accept-partial 1234567890
```

这会把 parent 标记为 `ACCEPTED_PARTIAL`，记录 manual resolution 元数据，不再继续期待剩余量成交。

### `reprice`

对一笔 tracked open `LIMIT` order 执行“先撤、再按新价格重提”的保守重定价。

```bash
qexec reprice 1234567890 --limit-price 9.50
qexec reprice client-order-id --limit-price 9.40 --broker alpaca-paper
```

`reprice` 不是 broker-native replace；它是 conservative cancel + resubmit。

### `retry-stale`

批量处理“过旧但仍未成交”的 tracked open orders：先撤单，再只对明确进入 `CANCELED` 的零成交订单发起重试。

```bash
qexec retry-stale
qexec retry-stale --older-than-minutes 15
qexec retry-stale --broker alpaca-paper
```

### `state-doctor`

检查本地 execution state 文件的一致性问题。

```bash
qexec state-doctor
qexec state-doctor --broker alpaca-paper
```

当前会检查 orphan child / parent / intent、duplicate fills、orphan broker orders、卡住的 kill switch、需要 operator 处理的 partial fill。

### `state-prune`

预览或清理旧的 terminal tracked records。

```bash
qexec state-prune --older-than-days 30
qexec state-prune --older-than-days 90 --apply
```

默认是 preview；只有加 `--apply` 才会写回状态文件。

### `state-repair`

对本地 state 应用保守修复。

```bash
qexec state-repair --clear-kill-switch
qexec state-repair --dedupe-fills --drop-orphan-fills
qexec state-repair --drop-orphan-terminal-broker-orders
```

至少要选择一个 repair action。

### `rebalance`

从 canonical `targets.json` 生成预览或进入 broker-backed 调仓路径。

```bash
qexec rebalance outputs/targets/2026-04-09.json
qexec rebalance outputs/targets/2026-04-09.json --account main
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --execute
qexec rebalance outputs/targets/2026-04-09.json --broker alpaca-paper --execute
qexec rebalance outputs/targets/2026-04-09.json --target-gross-exposure 0.9
```

## 行为约定

- `rebalance` 先做本地文件和 schema 校验，再触发 broker adapter。
- 非 `.json` 输入会被直接拒绝。
- schema-v1 / legacy ticker-list 不能作为 live execution 输入。
- `--execute` 缺省关闭；默认是 dry-run。
- real broker 的 `--execute` 额外要求 `QEXEC_ENABLE_LIVE=1`，并且 repo 根目录 `.env*` / `.envrc*` 里不能有 LongPort live 凭证。
- `longport-paper` 是 paper backend，依赖 `LONGPORT_ACCESS_TOKEN_TEST`，不要求 `QEXEC_ENABLE_LIVE=1`。
- `--broker` 默认读取本地配置里的 backend，没有配置时默认 `longport`。
- `--account` 会先走 adapter account/profile 校验；不支持的 label 会 fail fast，但当前并不提供真实多账户切换。
- `orders` / `exceptions` / `order` 读取的是本地 execution state，不会主动扫描 broker 全量订单。
- `retry` 当前只支持零成交 terminal tracked order。
- `reprice` 当前只支持零成交、仍然 open 的 tracked `LIMIT` order；实现方式是 cancel + resubmit。
- `cancel-rest`、`resume-remaining`、`accept-partial` 是当前的部分成交人工恢复链路。
- `rebalance` 每次运行都会写审计日志到 `outputs/orders/*.jsonl`。
- 活跃执行状态会持久化到 `outputs/state/*.json`，用于幂等、防重放和重启恢复。

## 测试运行

repo 内置三个外置工装：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario rebalance --print-json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
```

`smoke_operator_harness.py` 是最接近 operator workflow 的工装；需要留证时可以加 `--evidence-output`。
