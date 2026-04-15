# 执行底座

这份文档的职责是解释这个仓库的执行语义、关键不变量和设计边界。

如果你想知道命令怎么敲，看 [cli.md](cli.md)。
如果你想知道文件在哪，看 [architecture.md](architecture.md)。
如果你想知道测试怎么跑，看 [testing.md](testing.md)。

## 1. 这份文档回答什么

它主要回答四件事：

- 这个仓库到底负责执行链路的哪一段
- 订单生命周期里有哪些核心对象
- 本地 state、reconcile、risk、kill switch 各自扮演什么角色
- 为什么这个仓库刻意不做某些“看起来很平台”的东西

## 2. execution-only 边界

这个仓库只负责执行域：

- broker adapter 与 capability matrix
- 账户快照与行情读取
- `targets.json` 驱动的 rebalance / submit / reconcile
- tracked order 生命周期
- 订单执行的风控检查
- operator 恢复与本地状态维护
- 审计日志与 smoke harness

这个仓库不负责：

- 因子研究和回测
- 数据导入与特征工程
- 多账户统一路由中台
- 完整算法执行框架，例如 TWAP / POV

## 3. 核心对象

执行链路当前拆成这几层：

1. `OrderIntent`
   表达想买卖什么、为什么下这笔单，以及它来自哪个 target source / asof / input。
2. `ParentOrder`
   表达一次执行意图的总体状态，例如请求数量、已成交数量、剩余数量、当前汇总状态。
3. `ChildOrder`
   表达一次具体的 broker submit attempt。
4. `BrokerOrderRecord`
   表达 broker 返回的订单记录和 broker 侧状态。
5. `ExecutionFillEvent`
   表达已知成交事件。

这个拆分的意义不是为了抽象好看，而是为了回答真实问题：

- submit 前先落 `intent`，怎么防重复下单
- retry / reprice / resume-remaining 时，怎么保留 attempt 历史
- 系统重启后，怎么知道哪些订单还要继续跟
- reconcile 回来的状态和 fill，怎么映射回本地生命周期

## 4. 本地 state 为什么是基础设施

`outputs/state/*.json` 不是附属缓存，而是执行层的基础面。

它承担四个职责：

- 幂等：防止同一执行意图重复 submit
- 恢复：进程重启后还能找回 tracked order
- 运维：`orders` / `exceptions` / `order` / `retry` / `cancel-rest` 等命令都依赖它
- 对账：broker 状态和 fill 回来后，需要一个本地事实表来合并

也因此，这个仓库优先补的是 state doctor / prune / repair，而不是先上更重的持久层。

## 5. reconcile 的角色

`reconcile` 不是“顺手刷新一下”。

它负责把 broker 侧事实重新拉回本地：

- 刷新 tracked open orders
- 刷新 tracked closed orders
- 尝试回补缺失 fill
- 产出 delta / change view，告诉 operator 这次到底改了哪些单

换句话说，reconcile 是本地 state 和 broker state 之间的修正机制，而不是可有可无的辅助命令。

## 6. 风控与 kill switch

这个仓库做的是订单执行的风控管理。

当前风控管理主要关注：

- 单笔数量
- 单笔名义金额
- spread
- participation rate
- market impact

每个 gate 会产出结构化决策：

- `PASS`
- `BLOCK`
- `BYPASS`

如果 market data 不足，就记录 `BYPASS`，而不是伪造指标。

kill switch 也遵守 execution-only 语义：

- 它拦新的 submit
- 它不拦 query / reconcile / doctor / repair

这条区分很重要，因为 operator 需要在停掉新下单的同时继续排障和恢复。

## 7. operator 恢复链路

这个仓库现在有一条明确的人工接管路径：

- 看状态：`orders` / `exceptions` / `order`
- 刷状态：`reconcile`
- 做处置：`cancel` / `cancel-all` / `retry` / `reprice`
- 处理部分成交：`cancel-rest` / `resume-remaining` / `accept-partial`
- 维护本地事实：`state-doctor` / `state-prune` / `state-repair`

这里的关键词是 operator-supervised，不是全自动调度器。

## 8. preflight 和 smoke harness 的角色

`preflight` 是正式 CLI 能力，用来在不改 broker 状态的前提下检查 readiness。

`smoke_operator_harness.py` 则是固定 workflow 工装，用来重复验证：

- config
- account
- quote
- rebalance
- tracked order 查询
- reconcile
- exception queue
- 可选 cleanup / cancel-all

必要时还可以把这次 smoke 写成 evidence JSON，作为 broker-backed 验证记录。

对于 LongPort：

- `longport-paper` 现在已经适合用来做 broker-backed paper evidence
- `longport` real broker 则应该通过单独的 operator-supervised smoke playbook 来补实盘证据，而不是把 live secret 留在 repo 本地文件里

## 9. 当前设计取舍

这套底座的设计取舍：

- 优先把 execution 闭环跑通
- 优先补 operator recovery
- 优先补本地状态可诊断性
- 接受不同券商支持度和完成度不一致

所以它现在会保留：

- 单账户语义
- tracked-state 视图
- conservative cancel + resubmit
- file-based state

同时刻意不急着做：

- 多账户统一路由
- 全量 broker blotter
- event streaming
- 大而全 dashboard
- 完整算法执行框架
