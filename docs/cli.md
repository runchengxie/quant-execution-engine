# CLI 说明

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

按 broker 安装依赖：

```bash
uv sync --group dev --extra cli --extra longport
uv sync --group dev --extra cli --extra alpaca
uv sync --group dev --extra cli --extra full
```

如果没有在 `config/config.yaml` 显式设置 `broker.backend`，每次调用都需要传 `--broker`。

## 子命令

### `config`

显示当前券商后端、风控门禁、紧急停单和相关凭证摘要。

```bash
qexec config --broker longport-paper
qexec config --broker alpaca-paper
```

对于 LongPort，`config` 还会显示 App Key / Secret / Access Token / Region / Overnight 的命中来源，方便确认当前到底读到了仓库本地模拟盘配置，还是用户私有实盘配置。

### `preflight`

运行不会修改券商状态的就绪性检查。

```bash
qexec preflight --broker longport-paper
qexec preflight AAPL MSFT --broker longport-paper
qexec preflight --broker alpaca-paper
qexec preflight --broker longport-paper
```

当前会检查：

- 能力矩阵
- 实盘执行保护
- 手动紧急停单
- 本地状态紧急停单
- 账户解析
- 账户快照
- 行情 / 深度 / 成交量可达性

### `account`

查看账户概览。

```bash
qexec account --broker longport-paper
qexec account --broker longport-paper --format json
qexec account --broker longport-paper --funds
qexec account --broker longport-paper --positions
qexec account --broker alpaca-paper
qexec account --account main
```

### `quote`

查询实时行情。

```bash
qexec quote AAPL 700.HK --broker longport-paper
qexec quote AAPL --broker alpaca-paper
```

### `orders`

查看本地执行状态里已跟踪的券商订单。

```bash
qexec orders
qexec orders --status open
qexec orders --status failure
qexec orders --symbol AAPL
qexec orders --status open --symbol AAPL.US
qexec orders --broker alpaca-paper
```

### `exceptions`

查看本地执行状态中的异常队列，包含本地 `BLOCKED` / `FAILED` 和需要人工关注的券商状态。

```bash
qexec exceptions
qexec exceptions --status failure
qexec exceptions --status partially_filled,pending_cancel
qexec exceptions --symbol MSFT
qexec exceptions --broker alpaca-paper
```

### `order`

查看单笔已跟踪订单的本地执行详情。

```bash
qexec order 1234567890
qexec order child_abcd1234_1
qexec order client-order-id --broker alpaca-paper
```

输出会合并展示 intent / parent / child / broker / fill 信息，以及最近一次人工处置、归一化诊断和下一步建议。

### `reconcile`

手动触发一次券商对账，并把刷新后的状态写回 `outputs/state/*.json`。

```bash
qexec reconcile
qexec reconcile --broker alpaca-paper
qexec reconcile --account main
```

当前摘要会展示：

- 已跟踪订单变更数量
- 每笔订单的状态 / 成交量变化
- 新补录的成交
- 规范化告警码和下一步提示

### `cancel`

按已跟踪订单引用发起撤单。

```bash
qexec cancel 1234567890
qexec cancel child_abcd1234_1
qexec cancel client-order-id --broker alpaca-paper
```

### `cancel-rest`

撤掉一笔部分成交订单剩余的未成交部分。

```bash
qexec cancel-rest 1234567890
```

只支持：

- 已有部分成交
- 剩余量仍大于 0
- 券商侧当前仍是 open 状态

### `cancel-all`

撤销本地执行状态中仍然 open 的全部已跟踪券商订单。

```bash
qexec cancel-all
qexec cancel-all --broker alpaca-paper
```

### `retry`

重试一笔零成交的失败或已撤销已跟踪订单。

```bash
qexec retry 1234567890
qexec retry client-order-id --broker alpaca-paper
```

### `resume-remaining`

在部分成交后，为剩余量提交新的子订单尝试。

```bash
qexec resume-remaining 1234567890
```

只支持：

- 已有部分成交且仍有剩余量
- 原券商订单已不再 open
- 剩余量当前是整数股
- 尚未被 `accept-partial` 在本地关闭

### `accept-partial`

接受部分成交结果，并在本地关闭剩余量期待。

```bash
qexec accept-partial 1234567890
```

这会把 parent 标记为 `ACCEPTED_PARTIAL`，记录人工处置元数据，不再继续等待剩余量成交。

### `reprice`

对一笔已跟踪的 open `LIMIT` 订单执行“先撤单，再按新价格重提”的保守重定价。

```bash
qexec reprice 1234567890 --limit-price 9.50
qexec reprice client-order-id --limit-price 9.40 --broker alpaca-paper
```

`reprice` 采用保守的撤单后重提方式，不使用券商原生 replace。

### `retry-stale`

批量处理“过旧但仍未成交”的已跟踪 open 订单：先撤单，再只对明确进入 `CANCELED` 的零成交订单发起重试。

```bash
qexec retry-stale
qexec retry-stale --older-than-minutes 15
qexec retry-stale --broker alpaca-paper
```

### `state-doctor`

检查本地执行状态文件的一致性问题。

```bash
qexec state-doctor
qexec state-doctor --broker alpaca-paper
```

当前会检查孤儿 child / parent / intent、重复成交、孤儿券商订单、卡住的紧急停单，以及需要操作员处理的部分成交。

### `state-prune`

预览或清理旧的终态已跟踪记录。

```bash
qexec state-prune --older-than-days 30
qexec state-prune --older-than-days 90 --apply
```

默认是预览；只有加 `--apply` 才会写回状态文件。

### `state-repair`

对本地状态执行保守修复。

```bash
qexec state-repair --clear-kill-switch
qexec state-repair --dedupe-fills --drop-orphan-fills
qexec state-repair --drop-orphan-terminal-broker-orders
qexec state-repair --recompute-parent-aggregates
```

至少要选择一个修复动作。

### `rebalance`

从标准 `targets.json` 生成预览，或进入券商侧调仓路径。

```bash
qexec rebalance outputs/targets/2026-04-09.json
qexec rebalance outputs/targets/2026-04-09.json --account main
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --execute
qexec rebalance outputs/targets/2026-04-09.json --broker alpaca-paper --execute
qexec rebalance outputs/targets/2026-04-09.json --target-gross-exposure 0.9
```

## 行为约定

- `rebalance` 会先做本地文件和 schema 校验，再触发券商适配器。
- 非 `.json` 输入会被直接拒绝。
- schema-v1 / 旧版 ticker-list 不能作为实盘执行输入。
- `--execute` 默认关闭；不传时是预演。
- 实盘券商的 `--execute` 额外要求 `QEXEC_ENABLE_LIVE=1`，并且仓库根目录 `.env*` / `.envrc*` 里不能有 LongPort 实盘凭证。
- `longport-paper` 是模拟盘后端，依赖 `LONGPORT_ACCESS_TOKEN_TEST`，不要求 `QEXEC_ENABLE_LIVE=1`。
- `--broker` 默认读取本地配置里的后端；没有配置时会明确报错，要求显式设置 `broker.backend` 或传 `--broker`。
- `--account` 会先走适配器账户 / profile 校验；不支持的标签会快速失败，但当前并不提供真实多账户切换。
- `orders` / `exceptions` / `order` 读取的是本地执行状态，不会主动扫描券商全量订单。
- `retry` 当前只支持零成交的终态已跟踪订单。
- `reprice` 当前只支持零成交、仍然 open 的已跟踪 `LIMIT` 订单；实现方式是撤单后重提。
- `cancel-rest`、`resume-remaining`、`accept-partial` 是当前的部分成交人工恢复链路。
- `rebalance` 每次运行都会把审计日志写到 `outputs/orders/*.jsonl`。
- 活跃执行状态会持久化到 `outputs/state/*.json`，用于幂等、防重放和重启恢复。

## 测试运行

仓库内置三个外置工装：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario rebalance --print-json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

`smoke_operator_harness.py` 是最接近操作员流程的工装；需要留证时可以加 `--evidence-output`。

如果你想围绕 `longport-paper` 系统化做操作员失败场景冒烟，建议直接按 [longport-paper-failure-smoke.md](longport-paper-failure-smoke.md) 的场景执行。
