# 项目功能清单

> 这份 checklist 的目标不是把仓库推成全能平台，而是定义 execution-only 项目的完成线和克制边界。

## 状态标记

- `[x]` 已完成，仓库里已经落地
- `[~]` 已有骨架，但仍有明显 caveat 或证据不足
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
- 先把 LongPort real、`longport-paper` 和 Alpaca paper 跑稳，再考虑更广泛 broker 支持

如果未来目标变成研究 + 回测 + 实盘一体化平台，或者多 broker 多账户统一中台，这份清单就不再适用。

## 完成线定义

满足下面这些条件时，可以说这个仓库已经跑通执行闭环，但还没有开始再造车轮：

1. 能稳定完成 `account -> quote -> rebalance --execute -> reconcile` 主路径
2. 能在本地 execution state 中查看、撤销、重试、恢复和人工接管 tracked orders
3. 能在 broker 返回迟到、部分缺失、部分成交或需要人工刷新时完成基础恢复
4. 能清楚区分“已经落地的代码路径”和“已经被自动化充分证明的成熟度”

## 核心清单

### 1. 最小执行主路径

- `[x]` canonical schema-v2 `targets.json` 作为唯一 live execution 输入
- `[x]` `qexec config`
- `[x]` `qexec account`
- `[x]` `qexec quote`
- `[x]` `qexec rebalance` dry-run
- `[x]` `qexec rebalance --execute` broker-backed live-mode / paper-mode 路径
- `[x]` audit log 输出到 `outputs/orders/*.jsonl`
- `[x]` execution state 输出到 `outputs/state/*.json`
- `[x]` broker adapter capability matrix
- `[x]` 正式 `qexec preflight`

### 2. 订单生命周期与本地状态

- `[x]` order intent / parent order / child order / fill event 基本模型
- `[x]` 幂等提交，避免同一 intent 重复 submit
- `[x]` 本地 broker order 跟踪
- `[x]` reconcile 时刷新 tracked open orders
- `[x]` reconcile 时刷新 tracked closed orders
- `[x]` fill recovery 回补到本地 state
- `[x]` reconcile delta / change view
- `[x]` kill switch 和基础 risk gate
- `[x]` state doctor / prune / repair 基础工具

### 3. 运维与人工接管入口

- `[x]` `qexec orders`
- `[x]` `qexec exceptions`
- `[x]` `qexec order <order-ref>`
- `[x]` `qexec reconcile`
- `[x]` `qexec cancel <order-ref>`
- `[x]` `qexec cancel-all`
- `[x]` `qexec retry <order-ref>`
- `[x]` `qexec retry-stale --older-than-minutes N`
- `[x]` `qexec cancel-rest <order-ref>`
- `[x]` `qexec resume-remaining <order-ref>`
- `[x]` `qexec accept-partial <order-ref>`
- `[x]` 这些命令都只围绕 tracked orders 和本地 execution state

### 4. 现在已经补实的能力

- `[x]` broker rejection / warning 归一化输出
  当前 CLI summary、exception queue 和单笔详情会输出规范化 code 与 next-step hint。
- `[x]` 部分成交的人工恢复链路
  当前已经有 `cancel-rest`、`resume-remaining`、`accept-partial` 三条 operator 路径。
- `[x]` preflight 从 smoke harness 提升为正式 CLI 能力
- `[x]` reconcile 从纯计数摘要提升为变更视图
- `[x]` smoke operator harness 可选 evidence 输出

### 5. 当前仍然值得补的功能

- `[x]` `longport-paper` backend 已落地
  当前通过 `LONGPORT_ACCESS_TOKEN_TEST` 走 broker-backed paper submit/query/cancel/reconcile 路径，并已经有 operator-supervised paper smoke 证据链。
- `[~]` LongPort real broker submit/query/cancel/reconcile 的端到端证据仍不够扎实
  代码路径已经存在，但成熟度判断仍要看 operator-supervised smoke 和记载下来的证据链。
- `[~]` failure-mode regression 还应继续扩
  当前已经补了 live quote skip 逻辑、operator harness refusal/evidence 和部分成交恢复测试，但还缺更多真实失败模式。
- `[~]` broker-specific rejection taxonomy 仍可继续细化
  现在已经有统一诊断层，但更细的 broker 原始错误码归类仍有空间。

### 6. 有骨架，但还没到“完成”的项目

- `[~]` 多 broker 支持
  当前 LongPort 和 Alpaca paper 已有基础；未来可以加 IBKR，但不要求三家同成熟度。
- `[~]` child-order attempt 管理
  当前已经有 retry、reprice、resume-remaining，但还不是完整调度器。
- `[~]` 本地状态恢复
  现在对单机、低频、手工盯盘够用，但还不是更强持久层。

## 暂缓项

- `[-]` IBKR adapter 最小垂直切片
- `[-]` SQLite state store
- `[-]` broker event streaming
- `[-]` 更细的 metrics / alerts

这些都不是现在最缺的。当前更值钱的是把现有 execution 闭环的证据链和失败模式补实。

## 明确不做

- `[!]` research / backtest / alpha / data ingestion 层回流到这个仓库
- `[!]` 跨 broker 的真实多账户统一路由
- `[!]` 一上来统一所有 broker 的 order type / TIF / session 语义
- `[!]` 完整 TWAP / POV / algo execution framework
- `[!]` 大而全 dashboard / operator console
- `[!]` 把所有 broker 做成同一天毕业的一等公民

## 当前建议顺序

1. 继续补 LongPort real broker 的 submit/query/cancel/reconcile 证据链
2. 扩失败模式回归，优先覆盖拒单、迟到 fill、pending cancel、quote/region/network 异常
3. 视实际需要补 broker-specific rejection taxonomy
4. 继续把 Alpaca paper 当作稳定 regression / smoke 基线，而不是新的产品中心
5. 之后再考虑 IBKR 最小切片

## 维护原则

1. 新功能只有在直接提升执行闭环时，才进入 `[x]` / `[ ]` 区域。
2. 如果一个功能明显偏向平台化、统一化或大规模抽象，优先放进 `[-]` 或 `[!]`。
