## Why

`quant-execution-engine` 已经明确收敛为 execution-only 仓库，但当前 live execution 仍未形成真实闭环：`rebalance --execute` 还停留在模拟 `order_id`，`--account` 不切实际账户，也缺少 broker-neutral 的订单生命周期、对账恢复和低成本 paper 测试后端。下一步最有价值的工作不是把旧项目里的研究、回测、数据层搬回来，而是把执行链路做真、做稳、做可恢复。

这个 change 旨在把现有的 targets/account/quote/planner 主线，扩展成一个可持续演进的 execution foundation，同时保住 execution-only 边界，避免重新长成过度工程化的全能交易框架。

## What Changes

- 引入明确的 broker adapter 契约与 capability matrix，统一 `submit / cancel / query / list / reconcile` 等生命周期能力，并在 LongPort 之外增加 Alpaca paper adapter 作为低成本验证后端。
- 将现有模拟下单路径升级为真实的订单生命周期管理：区分 `order intent`、broker order、fill events 和 position state，并加入幂等、防重放、基础恢复和对账能力。
- 在 `plan -> validate -> submit` 之间增加轻量 pre-trade `risk gate`，优先覆盖执行层最关键的限制，如单笔数量/金额、spread、participation ratio 和基础 market impact 保护。
- 增加 paper smoke harness，提供最小 signal/target generators 与 paper 场景，用于验证执行闭环、订单状态机和 broker 差异；这些工装放在 core engine 之外。
- 保持 execution-only 边界，不把 research、AI、回测、历史数据中心、dashboard、部署编排或策略注册中心重新纳入底座。
- 扩展审计与状态持久化字段，为后续外置 execution observer / analytics 工具保留稳定输入，但不在本 change 中把分析平台并入核心包。

## Capabilities

### New Capabilities
- `broker-adapters`: 定义统一的 broker lifecycle 接口、显式 capability matrix，并提供 LongPort 与 Alpaca paper 实现。
- `order-lifecycle`: 管理 order intent、broker order、fill aggregation、parent/child order、幂等提交、恢复与 broker reconcile。
- `execution-risk-gates`: 在执行前做可配置的轻量风控拦截，覆盖 execution 层关键约束。
- `paper-smoke-harness`: 提供脱离核心引擎的 paper 测试工装，包括最小 signal harness、target generator 和场景测试入口。

### Modified Capabilities

None.

## Impact

- 受影响代码将集中在 `src/quant_execution_engine/broker/`、`rebalance.py`、`cli.py`、`models.py`、配置模型与审计输出。
- 预计新增 broker adapter 抽象、订单状态/恢复模块、风控模块，以及 paper harness 相关目录。
- 需要新增 Alpaca 相关依赖和配置文档，并补充以行为场景为主的 unit/integration/e2e 测试。
- 不修改 canonical schema-v2 `targets.json` 输入边界，但会扩展执行状态、审计和 broker 配置面。
