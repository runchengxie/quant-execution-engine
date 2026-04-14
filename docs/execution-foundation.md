# Execution Foundation

## Scope

这个仓库仍然是 execution-only。

这里新增的是执行底座能力，不是研究/回测平台回归：

- broker adapter 与 capability matrix
- order intent / broker order / fill event / reconcile
- file-backed state store
- execution risk gate
- manual / automatic kill switch
- signal-driven / target-driven smoke harness

## Broker Adapters

当前 backend：

- `longport`
- `alpaca-paper`

核心命令都可以通过 `--broker` 覆盖本地配置：

```bash
qexec quote AAPL --broker alpaca-paper
qexec account --broker longport
qexec rebalance outputs/targets/demo.json --broker alpaca-paper --execute
```

每个 adapter 都声明自己的能力矩阵，例如：

- 是否支持 live submit
- 是否支持 cancel / query / reconcile
- 是否支持 fractional
- 是否支持 extended hours
- 是否支持 account selection

## Order Lifecycle

执行链路现在明确拆成几层：

1. `OrderIntent`
2. `ParentOrder`
3. `ChildOrder`
4. `BrokerOrderRecord`
5. `ExecutionFillEvent`

这让引擎可以：

- 在 submit 前先持久化交易意图
- 用稳定 intent id 做幂等
- 在重启后恢复未完成 parent order
- 通过 reconcile 修正本地状态和 broker 状态差异

状态文件默认落在：

```text
outputs/state/*.json
```

## Risk Gates

live / paper 提交前会走轻量 risk gate。

当前重点是 execution 风险，而不是研究层风险：

- `max_qty_per_order`
- `max_notional_per_order`
- `max_spread_bps`
- `max_participation_rate`
- `max_market_impact_bps`

每个 gate 都会产出结构化决策：

- `PASS`
- `BLOCK`
- `BYPASS`

如果 market data 不足，例如拿不到 bid/ask 或 daily volume，引擎会记录 `BYPASS`，不会假造指标。

## Kill Switch

支持两类停机：

- 手动 kill switch
- 连续失败触发的自动 kill switch

手动 kill switch 默认看：

```text
QEXEC_KILL_SWITCH
```

设为 `1` / `true` / `yes` 时，新 submit 会被拦截，但现有状态仍可 query / reconcile。

## Audit Outputs

审计输出仍然写到：

```text
outputs/orders/*.jsonl
```

但现在会附带更多字段，例如：

- `intent_id`
- `parent_order_id`
- `child_order_id`
- `broker_order_id`
- `broker_status`
- `filled_quantity`
- `remaining_quantity`
- `avg_fill_price`
- `risk_decisions`
- `reconcile_status`

## Smoke Harness

外置工装：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json
```

这些脚本的职责是：

- 生成 deterministic targets
- 驱动 paper / dry-run 验证
- 测执行行为，不测 alpha

它们不是 repo 的正式策略层。
