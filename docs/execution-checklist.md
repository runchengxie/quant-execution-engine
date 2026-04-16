# 项目功能清单

> 本项目的目标是先把最基础的执行流程跑通，并支撑必要的技术验证。  
> 这份功能清单用于定义项目的完成线和克制边界。  
> 市面上已经有 QuantConnect/LEAN、vn.py 这类成熟执行框架，没有必要在这里重新造一个大而全的平台。

## 状态标记

- `[x]` 已完成，仓库里已经落地
- `[~]` 已有骨架，但仍有明显限制或证据不足
- `[ ]` 值得做，且仍在当前边界内
- `[-]` 暂缓，当前阶段优先级较低
- `[!]` 明确不做，避免仓库重新膨胀

## 当前目标边界

这份功能清单默认对应下面这个目标：

- 量化交易执行仓库
- 单账户语义优先
- 低频或半自动执行场景
- 以 `targets.json` 驱动券商侧调仓 / 提交 / 对账
- 人工可介入的运维链路
- 先把 LongPort 实盘、`longport-paper` 和 Alpaca 模拟盘跑稳，再考虑更广的券商支持

如果未来目标变成“研究 + 回测 + 实盘”一体化平台，或者跨券商多账户统一中台，这份清单就不再适用。

## 完成线定义

满足下面这些条件时，可以说这个仓库已经跑通了执行闭环，但还没有开始重新造轮子：

1. 能稳定完成 `account -> quote -> rebalance --execute -> reconcile` 主路径
2. 能在本地执行状态中查看、撤销、重试、恢复和人工接管已跟踪订单
3. 能在券商返回迟到、部分缺失、部分成交或需要人工刷新时完成基础恢复
4. 能清楚区分“代码路径已经落地”和“成熟度已经被充分自动化证明”

## 核心清单

### 1. 最小执行主路径

- `[x]` 基于指定格式的持仓清单 `targets.json` 作为唯一实盘下单输入
- `[x]` `qexec config`
- `[x]` `qexec account`
- `[x]` `qexec quote`
- `[x]` `qexec rebalance` 预演
- `[x]` `qexec rebalance --execute` 的券商侧实盘 / 模拟盘路径
- `[x]` 审计日志输出到 `outputs/orders/*.jsonl`
- `[x]` 执行状态输出到 `outputs/state/*.json`
- `[x]` 券商适配器能力矩阵
- `[x]` 正式 `qexec preflight`

### 2. 订单生命周期与本地状态

- `[x]` order intent / parent order / child order / fill event 基本模型
- `[x]` 幂等提交，避免同一 intent 重复 `submit`
- `[x]` 本地券商订单跟踪
- `[x]` `reconcile` 时刷新已跟踪 open orders
- `[x]` `reconcile` 时刷新已跟踪 closed orders
- `[x]` 成交回补到本地状态
- `[x]` `reconcile` 差异 / 变更视图
- `[x]` 紧急停单和基础风控门禁
- `[x]` `state doctor / prune / repair` 基础工具

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
- `[x]` 这些命令都只围绕已跟踪订单和本地执行状态

### 4. 现在已经补实的能力

- `[x]` 券商拒单 / 告警归一化输出  
  当前 CLI 摘要、异常队列和单笔详情会输出规范化代码与下一步提示。
- `[x]` 部分成交的人工恢复链路  
  当前已经有 `cancel-rest`、`resume-remaining`、`accept-partial` 三条操作员路径。
- `[x]` `preflight` 从冒烟工装提升为正式 CLI 能力
- `[x]` `reconcile` 从纯计数摘要提升为变更视图
- `[x]` 冒烟操作员工装支持可选证据输出
- `[x]` LongPort 模拟盘 / 实盘配置隔离与来源可见性  
  `longport-paper` 默认优先仓库本地 `.env`，LongPort 实盘默认优先 `~/.config/qexec/longport-live.env`；`qexec config` 会显示命中来源。

### 5. 当前仍值得继续补的功能

- `[x]` `longport-paper` 后端已落地  
  当前通过 `LONGPORT_ACCESS_TOKEN_TEST` 走券商侧模拟盘 `submit/query/cancel/reconcile` 路径，并已经有人工监督的模拟盘冒烟证据链。
- `[~]` LongPort 实盘 `submit/query/cancel/reconcile` 的端到端证据仍不够扎实  
  截至 2026-04-15，`config / preflight / account / quote` 已人工验证通过；下一步仍是补最小实盘 `rebalance --execute` 证据。
- `[~]` 失败场景回归还应继续扩  
  当前已经补了实盘行情跳过逻辑、操作员工装拒绝路径 / 证据输出，以及部分成交恢复测试，但还缺更多真实失败场景。
- `[~]` 券商特定拒单分类仍可继续细化  
  现在已经有统一诊断层，但更细的券商原始错误码归类仍有空间。

### 6. 有骨架，但还没到“完成”的项目

- `[~]` 多券商支持  
  当前 LongPort 和 Alpaca 模拟盘已有基础；未来可以加 IBKR，但不要求三家同成熟度。
- `[~]` 子订单尝试管理  
  当前已经有 `retry`、`reprice`、`resume-remaining`；完整调度器仍未展开。
- `[~]` 本地状态恢复  
  现在对单机、低频、手工盯盘场景已经够用；更强的持久层还未展开。

## 暂缓项

- `[-]` IBKR 适配器最小垂直切片
- `[-]` SQLite 状态存储
- `[-]` 券商事件流
- `[-]` 更细的指标 / 告警

当前更优先的是把现有执行闭环的证据链和失败场景补实。

## 明确不做

- `[!]` 把研究 / 回测 / alpha / 数据导入层回流到这个仓库
- `[!]` 跨券商的真实多账户统一路由
- `[!]` 一开始就统一所有券商的 order type / TIF / session 语义
- `[!]` 完整的 TWAP / POV / 算法执行框架
- `[!]` 大而全的仪表板 / 操作员控制台
- `[!]` 把所有券商做成同一天毕业的一等公民

## 当前建议顺序

1. 继续补 LongPort 实盘 `submit/query/cancel/reconcile` 证据链  
   当前只读验证已完成，下一步是最小实盘冒烟和证据留档。
2. 扩失败场景回归，优先覆盖拒单、迟到成交、`pending cancel`、行情 / 区域 / 网络异常
3. 视实际需要补券商特定拒单分类
4. 继续把 Alpaca 模拟盘定位为稳定的回归 / 冒烟基线
5. 之后再考虑 IBKR 最小切片

## 维护原则

1. 新功能只有在直接提升执行闭环时，才进入 `[x]` / `[ ]` 区域。
2. 如果一个功能明显偏向平台化、统一化或大规模抽象，优先放进 `[-]` 或 `[!]`。
