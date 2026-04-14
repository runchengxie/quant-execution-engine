# 执行底座 (Execution Foundation)

## 适用范围

这个仓库主要用于订单执行

- 券商适配器与能力矩阵
- 订单意图/ 券商订单 / 成交事件 / 对账
- 基于文件的状态存储
- 执行端风控网关
- 手动 / 自动紧急开关
- 信号驱动 / 目标驱动的冒烟测试工装

## 券商适配

当前支持的后端 (backend)：

- `longport`
- `alpaca-paper`

核心命令都可以通过 `--broker` 覆盖本地配置：

```bash
qexec quote AAPL --broker alpaca-paper
qexec account --broker longport
qexec rebalance outputs/targets/demo.json --broker alpaca-paper --execute
```

每个适配都会声明自己的能力矩阵，例如：

- 是否支持实盘提交 (live submit)
- 是否支持撤单 / 查询 / 对账 (cancel / query / reconcile)
- 是否支持碎股交易 (fractional)
- 是否支持盘外交易 (extended hours)
- 是否支持多账户选择 (account selection)

## 订单生命周期 (Order Lifecycle)

执行链路现在明确拆分为以下几层：

1. `OrderIntent` (交易意图)
2. `ParentOrder` (母单)
3. `ChildOrder` (子单)
4. `BrokerOrderRecord` (券商订单记录)
5. `ExecutionFillEvent` (成交事件)

这种设计让引擎可以：

- 在 submit 之前先持久化交易意图
- 利用稳定的 intent id 保证幂等性
- 在系统重启后恢复未完成的母单 (parent order)
- 通过 reconcile 修正本地状态与 broker 状态间的差异，并补录 tracked closed orders 的 fills

状态文件默认落盘至：

```text
outputs/state/*.json
```

## 风控网关

实盘 (live) / 模拟盘 (paper) 提交前会经过一层轻量的风控。

当前的重点是执行端风险，而不是研究层面的风险：

- `max_qty_per_order` (单笔最大数量)
- `max_notional_per_order` (单笔最大名义价值)
- `max_spread_bps` (最大买卖价差)
- `max_participation_rate` (最大参与率)
- `max_market_impact_bps` (最大市场冲击)

每个 gate 都会产出结构化的决策结果：

- `PASS` (通过)
- `BLOCK` (拦截)
- `BYPASS` (跳过)

如果行情数据 (market data) 不足，例如拿不到 bid/ask 或日成交量 (daily volume)，引擎会记录 `BYPASS`，而不会去伪造指标。

## 紧急开关 (Kill Switch)

支持两类停机机制：

- 手动的 kill switch
- 连续失败触发的自动 kill switch

手动 kill switch 默认检查环境变量：

```text
QEXEC_KILL_SWITCH
```

当设为 `1` / `true` / `yes` 时，新的 submit 会被拦截，但现有状态仍可正常进行 query / reconcile。

## 审计输出 (Audit Outputs)

审计日志仍然输出到：

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

## 测试脚本

外置的测试工装脚本：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json
```

这些脚本的职责是：

- 生成确定性的目标
- 驱动模拟盘 (paper) / 试运行 (dry-run) 的验证流程
- 仅测试执行层面的行为，不测试策略逻辑

## 运维入口

除了 `rebalance` 之外，CLI 现在还提供：

```bash
qexec orders
qexec order <order-ref>
qexec reconcile
qexec cancel <order-ref>
qexec cancel-all
qexec retry <order-ref>
```

- `orders` 用于查看本地 execution state 中跟踪的 broker orders
- `order` 用于查看单笔 tracked order 的完整本地生命周期信息
- `reconcile` 用于主动刷新 broker open/closed order 状态，并把补录的 fills 写回状态文件
- `cancel` 用于按 tracked `broker_order_id` / `client_order_id` / `child_order_id` 发起撤单，并同步更新本地状态
- `cancel-all` 用于批量撤销本地 execution state 中仍然 open 的 tracked broker orders
- `retry` 用于重试零成交的失败/撤销 tracked order，并创建新的 child attempt
