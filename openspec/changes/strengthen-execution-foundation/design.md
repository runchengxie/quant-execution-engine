## Context

当前仓库已经明确是 execution-only：输入边界是 canonical schema-v2 `targets.json`，主链路集中在账户快照、行情、调仓计划、diff 预览和审计日志。现状的主要缺口不在“功能数量”，而在“执行闭环真实性”：`rebalance --execute` 仍通过 `LongPortClient.place_order()` 返回模拟 `order_id`，`Order` 同时承载意图与结果，`--account` 只记日志不切账户，也没有独立的 reconcile / recovery / idempotency 机制。

这次变更是跨模块设计：它会影响 `cli.py`、`rebalance.py`、`models.py`、`broker/`、配置层、审计输出和测试结构，并引入新的外部依赖（Alpaca paper）。仓库边界同时要求我们不能用回测框架、历史数据库或 dashboard 去“解决”执行问题。

## Goals / Non-Goals

**Goals:**
- 把 broker 访问从 LongPort 专用工具箱提升为统一 lifecycle adapter。
- 让 live execution 走真实 submit/query/cancel/list/reconcile 闭环，不再使用模拟 `order_id` 冒充 live。
- 将订单建模拆分为 `order intent -> broker order -> fill events -> position state`，支持幂等、防重放、恢复和基础 parent/child order。
- 在执行前增加轻量 risk gate，并提供可显式触发的 kill switch。
- 引入 Alpaca paper 作为 broker adapter 层的验证后端，并提供最小 smoke harness 驱动执行闭环。
- 保持 execution-only 边界，延续当前 `targets/account/quote/planner` 主线。

**Non-Goals:**
- 不把研究、AI、回测、历史数据导入、TimescaleDB、dashboard 或多服务部署编排带回本仓库。
- 不在本次变更中实现完整的事件驱动异步交易内核；首版以显式 submit/poll/reconcile 为主。
- 不把 smoke harness 演化成策略框架或策略注册中心。
- 不在核心包内加入 post-trade performance analytics；仅补足外置 observer 所需的稳定审计输入。
- 不修改 canonical schema-v2 `targets.json` 的输入契约。

## Decisions

### 1. 引入 broker adapter 契约与 capability matrix

核心执行链路将只依赖统一的 broker 接口，例如 `get_account()`, `get_positions()`, `submit_order()`, `get_order()`, `cancel_order()`, `list_open_orders()`, `reconcile()`，同时要求每个 adapter 声明能力矩阵，例如 fractional、short、lot size、支持的 order type / TIF、extended hours、account profile 支持情况。

这样做可以把 LongPort 和 Alpaca paper 放在同一执行面下，也让 `--account` 从“兼容日志参数”升级为显式的 account/profile 解析行为：支持则切换，不支持则失败，不再静默降级。

备选方案是继续让 `rebalance.py` 直接调用 `LongPortClient` 并在内部堆分支。这会让 Alpaca 接入、broker 差异治理、测试替身和后续扩展都继续耦合在单一实现里，因此不采用。

### 2. 将订单域拆分为意图、券商订单、成交事件和父子单

当前 `Order` dataclass 混合了计划输入、执行状态和券商返回值，无法可靠表示“我想做什么”和“broker 实际发生了什么”。新设计将引入：
- `OrderIntent`：由 rebalance planner 或 smoke harness 产生的稳定交易意图，带稳定 intent id。
- `BrokerOrder`：某次提交到具体 broker 的订单记录，带 broker order id、状态和 adapter 元数据。
- `FillEvent`：可追加的成交事件，用于累计成交和部分成交处理。
- `ParentOrder` / `ChildOrder`：用于支持拆单、未完成数量跟踪与跨运行恢复。

备选方案是继续复用现有 `Order` 并只追加字段。这会延续状态语义混杂的问题，且不利于幂等和恢复，因此不采用。

### 3. 首版采用文件化状态存储，而不是数据库

为了支持恢复和 reconcile，需要在审计日志之外增加最小持久化状态。首版使用本地文件存储即可，例如在 `outputs/` 下新增执行状态目录，记录活跃 parent/child order、最近 reconcile 时间、已确认 fills 和 account/profile 绑定。写入必须采用原子替换，避免进程中断产生半写文件。

备选方案是直接引入 SQLite、Redis 或 TimescaleDB。虽然这些方案对复杂系统更强，但会立刻扩大仓库职责，并把当前 execution-only 底座拖回基础设施工程，因此首版不采用。

### 4. 先实现 poll + reconcile 闭环，再把 stream 作为可选增强

首版执行链路以同步 submit、显式 query/list、定时 reconcile 和超时 cancel 为核心。设计上保留 adapter 级 `stream_events()` 扩展点，但不要求首版围绕 WebSocket 构建统一 async runtime。这样可以先把核心闭环做稳，再决定是否接入实时流。

备选方案是立即设计全异步事件总线和 streaming-first 状态机。这会在真实 submit 仍未闭环时引入过高复杂度，因此不采用。

### 5. 把 risk gate 做成独立执行前校验链，并附带 kill switch

风控不应散落在 broker adapter 和 planner 的隐式逻辑里。新设计会在 `plan -> validate -> submit` 之间增加独立的 `RiskGate` 链，最先落地的规则包括：
- 最大单笔数量 / 金额
- spread guard
- participation ratio guard
- 基础 market impact estimate
- 手动 kill switch 和连续失败触发的保护停机

每条规则都必须返回结构化决策与原因，供审计和测试消费。

备选方案是只依赖 broker 风控或继续用本地零散限制。这不能满足 execution 层“在不该发时拒绝发”的职责，因此不采用。

### 6. smoke harness 放在核心包之外，只作为验证工装

为了验证执行引擎不是“只会读 JSON 和写日志”，本次变更会增加最小 signal harness、target generator 和 paper 场景，但它们不进入核心 domain。推荐位置是 `examples/`、`project_tools/` 或独立的 smoke 目录，并通过 CLI 或脚本驱动 engine。

备选方案是把 PATF 中的策略框架、回测脚本或 dashboard 整体迁回仓库。这会破坏 execution-only 边界，因此不采用。

## Risks / Trade-offs

- [Broker 能力不一致导致行为分叉] → 用 capability matrix 明确差异；当请求超出 broker 能力时 fail fast，而不是悄悄降级。
- [状态文件损坏或 schema 演进困难] → 使用小而稳定的状态模型、版本字段和原子写入；审计日志保持追加式，便于恢复和排障。
- [部分成交、撤单失败、重启恢复让状态机复杂化] → 先聚焦 parent/child 基本流和 poll-based reconcile，把 fill 聚合和恢复放在一等路径里测试。
- [Alpaca paper 容易被误解为成交质量代表] → 明确将其定位为系统行为验证后端，不把 paper 盈亏或 fill quality 当成主要验收标准。
- [增加新模块后 CLI 迁移风险上升] → 先在现有 `qexec rebalance` 路径后面插入新生命周期服务，保留 dry-run，不做激进 CLI 改写。

## Migration Plan

1. 增加 broker adapter 抽象、capability matrix 和最小执行状态模型，但先保留现有 CLI 外观。
2. 将 `rebalance --execute` 接到新的 order lifecycle service；对不支持真实 submit 的 broker 显式报错，而不是返回模拟成功。
3. 扩展审计输出和本地状态存储，保证新旧日志消费者仍可读取原有 `outputs/orders/*.jsonl`。
4. 接入 Alpaca paper adapter，并提供最小 smoke harness 与场景测试。
5. 在 LongPort 和 Alpaca paper 上补齐 query/cancel/list/reconcile 行为测试后，再默认推荐 `--execute` 用于真实/paper 闭环验证。
6. 如出现严重问题，回滚策略是保留 dry-run 能力、关闭 live submit 入口，并继续输出 planning/audit 结果。

## Open Questions

- LongPort SDK 当前可用的 order query / cancel / list / fill 明细接口具体边界是什么，是否足以支撑首版 reconcile？
- `--account` 应映射为 broker account id、配置 profile，还是更高层的 execution venue label？
- parent/child order 的首版是否只做单次 child submit + 剩余量跟踪，还是同时实现基础时间分片逻辑？
- Alpaca adapter 首版是否支持 fractional 与 extended hours，还是先限制为最小 market/limit 基础通路？
- kill switch 的触发策略应全部来自配置，还是先内置一组保守默认值？
