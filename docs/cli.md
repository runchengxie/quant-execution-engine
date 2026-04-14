# CLI

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

查看本地执行状态里跟踪的 broker orders。

```bash
qexec orders
qexec orders --status open
qexec orders --status failure
qexec orders --symbol AAPL
qexec orders --status open --symbol AAPL.US
qexec orders --broker alpaca-paper
qexec orders --account main
```

### `exceptions`

查看本地 execution state 中的异常队列，包含本地 `BLOCKED/FAILED` 和需要人工关注的 broker 状态。

```bash
qexec exceptions
qexec exceptions --status failure
qexec exceptions --status partially_filled,pending_cancel
qexec exceptions --symbol MSFT
qexec exceptions --status failure --symbol MSFT.US
qexec exceptions --broker alpaca-paper
```

### `order`

查看单笔 tracked order 的本地执行详情。

```bash
qexec order 1234567890
qexec order child_abcd1234_1
qexec order client-order-id --broker alpaca-paper
```

### `reconcile`

手动触发一次 broker reconcile，并把刷新后的状态写回 `outputs/state/*.json`。

```bash
qexec reconcile
qexec reconcile --broker alpaca-paper
qexec reconcile --account main
```

### `cancel`

按本地 execution state 中已跟踪的 order ref 发起撤单。

```bash
qexec cancel 1234567890
qexec cancel child_abcd1234_1
qexec cancel client-order-id --broker alpaca-paper
```

### `cancel-all`

撤销本地 execution state 中仍然 open 的全部 tracked broker orders。

```bash
qexec cancel-all
qexec cancel-all --broker alpaca-paper
qexec cancel-all --account main
```

### `retry`

重试一笔零成交的失败/撤销 tracked order。

```bash
qexec retry 1234567890
qexec retry child_abcd1234_1
qexec retry client-order-id --broker alpaca-paper
```

### `reprice`

对一笔 tracked open `LIMIT` order 执行“先撤、再按新价格重提”的保守重定价。

```bash
qexec reprice 1234567890 --limit-price 9.50
qexec reprice child_abcd1234_1 --limit-price 9.45
qexec reprice client-order-id --limit-price 9.40 --broker alpaca-paper
```

### `retry-stale`

批量处理“过旧但仍未成交”的 tracked open orders：先撤单，再只对明确进入 `CANCELED` 的零成交订单发起重试。

```bash
qexec retry-stale
qexec retry-stale --older-than-minutes 15
qexec retry-stale --broker alpaca-paper
```

### `rebalance`

从 canonical `targets.json` 生成预览或进入 live-mode 调仓路径。

```bash
qexec rebalance outputs/targets/2026-04-09.json
qexec rebalance outputs/targets/2026-04-09.json --account main
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --execute
qexec rebalance outputs/targets/2026-04-09.json --broker alpaca-paper --execute
qexec rebalance outputs/targets/2026-04-09.json --target-gross-exposure 0.9
```

## 行为约定

- `rebalance` 先做本地文件和格式校验，再触发 broker adapter 相关逻辑。
- 非 `.json` 输入会被直接拒绝。
- schema-v1 / legacy ticker-list 不能作为 live execution 输入。
- `--execute` 缺省关闭；默认是 dry-run。
- real broker 的 `--execute` 额外要求 `QEXEC_ENABLE_LIVE=1`。
- `--broker` 默认读取本地配置里的 backend，没有配置时默认 `longport`。
- `--account` 会先走 adapter account/profile 校验；不支持的 label 会 fail fast。
- `orders` 读取的是本地 execution state 中已跟踪的 broker order 记录，不会主动联网；`--status` 支持 `open` / `terminal` / `failure` / `success` / `exception` 或精确状态，`--symbol` 支持 bare ticker 或 canonical symbol。
- `exceptions` 读取的是本地 execution state 中需要人工关注的 tracked order 记录，默认会包含 `BLOCKED` / `FAILED` / `REJECTED` / `EXPIRED` / `PARTIALLY_FILLED` / `PENDING_CANCEL` / `WAIT_TO_CANCEL`；`--symbol` 同样支持 bare ticker 或 canonical symbol。
- `order` 会把 intent / parent / child / broker / fill 这些本地生命周期信息合并展示出来，也会带出 target source/asof/input 和最近一次 reprice 元数据。
- `reconcile` 会主动访问 broker，刷新 tracked open/closed orders，并尝试补录缺失的 fills。
- `cancel` 支持 `broker_order_id`、`client_order_id` 或 `child_order_id`，撤单后会把本地 state 同步刷新。
- `cancel-all` 只处理本地 execution state 中仍然 open 的 tracked order，不会扫描 broker 全量订单。
- `retry` 当前只支持零成交的 `FAILED` / `CANCELED` / `REJECTED` / `EXPIRED` tracked order；部分成交续单还没有实现。
- `reprice` 当前只支持零成交、仍然 open 的 tracked `LIMIT` order；实现方式是先撤后重提，不依赖 broker 原生 replace。
- `retry-stale` 只处理零成交、仍然 open、且超过阈值的 tracked order；如果撤单后状态不是明确 `CANCELED`，不会继续自动重提。
- `--execute` 会进入 broker-backed submit/query/reconcile 路径，并写出 richer audit/state 输出。
- real broker 的 `--execute` 会扫描 repo 根目录 `.env*` / `.envrc*`；如果发现 LongPort live 凭证，CLI 会直接拒绝执行。
- live / paper 下单前会经过 execution risk gate；如果 spread、参与率、impact 或 kill switch 拦截，CLI 输出里会看到 `BLOCKED` 和具体原因。
- `rebalance` 每次运行都会写审计日志到 `outputs/orders/*.jsonl`。
- 活跃执行状态会持久化到 `outputs/state/*.json`，用于幂等、防重放和重启恢复。

## 测试运行

repo 内置两个外置工装：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario rebalance --print-json
```

它们会生成 canonical `targets.json`，必要时还能直接调用 `qexec rebalance`。这些工装用于验证执行行为。
