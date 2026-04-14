# 项目功能清单

> 因为实际上市面上有很多例如vn.py和QuantConnect/LEAN这样的开源框架，这个项目的存在目的主要是对了解和熟悉量化投资订单执行流程有感性认识，快速部署的测试夹具，或者是跑通量化投研->订单执行的快速验证

这个文档的目标是给该订单执行项目定义一份清晰的完成线：

- 我们要把订单执行流程跑通
- 我们要有最基本的运维、恢复和排障能力
- 我们不必为了框架感过早扩成 research / backtest / 多账户中台 / 全能 OMS

## 状态标记

- `[x]` 已完成，仓库里已经落地
- `[~]` 已有骨架，但仍有明显 caveat
- `[ ]` 值得做，且仍在当前边界内
- `[-]` 暂缓，不是当前阶段优先项
- `[!]` 明确不做，避免仓库重新膨胀

## 当前目标边界

这份 checklist 默认对应的是下面这个目标：

- execution-only 仓库
- 单账户语义优先
- 低频或半自动执行场景
- 以 `targets.json` 驱动 broker-backed rebalance / submit / reconcile
- 人工可介入的运维链路
- 把 Alpaca paper 和 LongPort 跑稳，其次对 Interactive Broker 进行基础的支持

如果未来目标变成研究 + 回测 + 实盘一体化平台或者多券商多账户统一中台，这份清单不再适用，应该单独开新路线，甚至建议直接迁移至 vn.py 或 LEAN 等平台

## 完成线定义

满足下面这些条件时，可以说这个仓库已经达到跑通流程，但还没有开始再造车轮的状态：

1. 能稳定完成 `account -> quote -> rebalance --execute -> query/reconcile` 主路径
2. 能在本地 execution state 中查看、撤销、重试和恢复 tracked orders
3. 能在 broker 返回迟到、部分缺失或需要人工刷新时，完成基础 reconcile 和 fill recovery
4. 能清楚区分当前值得做的执行功能和暂时不做的系统扩张

## 核心清单

### 1. 最小执行主路径

- `[x]` canonical schema-v2 `targets.json` 作为唯一 live execution 输入
- `[x]` `qexec config`
- `[x]` `qexec account`
- `[x]` `qexec quote`
- `[x]` `qexec rebalance` dry-run
- `[x]` `qexec rebalance --execute` live-mode / paper-mode 路径
- `[x]` audit log 输出到 `outputs/orders/*.jsonl`
- `[x]` execution state 输出到 `outputs/state/*.json`
- `[x]` broker adapter capability matrix

### 2. 订单生命周期与本地状态

- `[x]` order intent / parent order / child order / fill event 基本模型
- `[x]` 幂等提交，避免同一 intent 重复 submit
- `[x]` 本地 broker order 跟踪
- `[x]` reconcile 时刷新 tracked open orders
- `[x]` reconcile 时刷新 tracked closed orders
- `[x]` fill recovery 回补到本地 state
- `[x]` kill switch 和基础 risk gate

### 3. 运维与人工接管入口

- `[x]` `qexec orders`
- `[x]` `qexec order <order-ref>`
- `[x]` `qexec reconcile`
- `[x]` `qexec cancel <order-ref>`
- `[x]` `qexec cancel-all`
- `[x]` `qexec retry <order-ref>`
- `[x]` `qexec retry-stale --older-than-minutes N`
- `[x]` 这些命令都只围绕 tracked orders

### 4. 当前仍然值得补的功能

下面这些都还在合理边界内，做了不算过度工程化：

- `[~]` LongPort live submit/query/cancel/reconcile 的端到端证据还不够扎实
- `[ ]` stale limit order 的 replace / reprice，而不只是 cancel + retry
- `[ ]` 更明确的 exception queue 视图
  例如快速列出 `FAILED` / `BLOCKED` / `PARTIALLY_FILLED` / `PENDING_CANCEL` 的 tracked orders
- `[ ]` 按状态筛选的 operator 命令
  例如只看 open / failed / blocked orders
- `[ ]` 更明确的 broker rejection / warning 归一化输出
- `[ ]` Alpaca paper 的重复 smoke 验证说明
  重点不是新功能，而是把 paper 验证路径固定成一套标准回归流程

### 5. 有骨架，但还没到“完成”的项目

这些是已经露出抽象、但仍应克制推进的地方：

- `[~]` 多 broker 支持
  当前 LongPort 和 Alpaca paper 已有基础；未来可以加 IBKR，但不要求三家同成熟度
- `[~]` child-order attempt 管理
  当前已经有 retry 和 stale retry，但还不是完整的 scheduler
- `[~]` 本地状态恢复
  现在对单机、低频、手工盯盘够用，但还不是更强持久层

## 暂缓项

- `[-]` IBKR adapter 最小垂直切片
  可以做，但建议放在 Alpaca paper 和 LongPort 更稳之后
- `[-]` SQLite state store
  有价值，但优先级低于真实 broker 验证和 operator recovery
- `[-]` broker event streaming
  比轮询 reconcile 更好，但不是当前最小闭环必需
- `[-]` 更细的 metrics / alerts
  先把执行语义补稳，再谈运行期观测

## 明确不做

这些如果现在开始做，就很容易从跑通流程滑向重新造车轮：

- `[!]` research / backtest / alpha / data ingestion 层回流到这个仓库
- `[!]` 跨 broker 的真实多账户统一路由
- `[!]` 一上来统一所有 broker 的 order type / TIF / session 语义
- `[!]` 完整 TWAP / POV / algo execution framework
- `[!]` 大而全 dashboard / operator console
- `[!]` 把三家 broker 做成同一天毕业的一等公民

## 当前建议顺序

如果把这份文档当 to-do list，建议按这个顺序推进：

1. 先把 Alpaca paper 路径反复跑稳，作为标准 smoke 环境
2. 把 LongPort live submit/query/cancel/reconcile 的端到端证据补实
3. 补 `replace / reprice` 这种比 `cancel + retry` 更贴近真实运维的能力
4. 补更清楚的 exception queue / 状态筛选视图
5. 之后再决定要不要做 IBKR 最小 adapter

## 使用方式

维护这份清单时，建议遵守两个原则：

1. 新功能只有在直接提升执行闭环时，才放进 `[ ]` 区域。
2. 如果一个功能开始明显偏向平台化、统一化或大规模抽象，就先放进 `[-]` 或 `[!]`，不要直接进入当前 开发待办。
