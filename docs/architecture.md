# 项目架构

## 定位

`quant_execution_engine` 是一个 execution-only 引擎。

它负责：

- broker adapter、能力矩阵与凭证封装
- 账户快照与行情抓取
- 调仓计划生成与 diff 预览
- dry-run / live / paper 调仓流程
- order intent / parent-child order / fill / reconcile 生命周期
- execution risk gate 与 kill switch
- preflight、状态维护和 operator 终端输出
- 审计输出、状态持久化与 smoke harness

它不负责：

- research / backtest / alpha
- 数据导入或因子计算
- 多账户统一路由中台
- 完整 TWAP / POV / algo execution framework

## 包结构

```text
src/quant_execution_engine/
  __init__.py
  __main__.py
  cli.py
  config.py
  paths.py
  logging.py
  models.py
  fees.py
  fx.py
  targets.py
  account.py
  rebalance.py
  execution.py
  execution_state.py
  diagnostics.py
  guards.py
  preflight.py
  risk.py
  state_tools.py
  broker/
    __init__.py
    base.py
    factory.py
    alpaca.py
    _stubs.py
    longport_adapter.py
    longport_credentials.py
    longport.py
  renderers/
    __init__.py
    diff.py
    jsonout.py
    table.py
project_tools/
  smoke_signal_harness.py
  smoke_target_harness.py
  smoke_operator_harness.py
```

## 分层说明

- `cli.py`
  负责参数解析、broker/backend 选择、命令分发和错误码收口，包括 `preflight`、operator 恢复命令和 state maintenance 命令。
- `broker/base.py` / `broker/factory.py`
  定义 broker lifecycle 契约、capability matrix 和 backend 选择逻辑。
- `broker/longport.py` / `broker/longport_adapter.py` / `broker/alpaca.py`
  分别负责 LongPort SDK wrapper、LongPort real/paper adapter，以及 Alpaca paper adapter 实现。
- `broker/longport_credentials.py`
  负责 LongPort real / paper 的凭证解析、paper/live 配置隔离和 placeholder 回避。
- `account.py`
  负责通过 adapter 获取账户快照与行情查询。
- `rebalance.py`
  负责目标仓位计算、订单规划、执行入口和审计日志。
- `execution.py`
  负责订单提交流程、reconcile、partial-fill 恢复和 tracked-order operator 行为。
- `execution_state.py`
  负责 execution lifecycle dataclass、状态常量和 file-backed state store。
- `diagnostics.py`
  负责把 broker / local order 的异常状态和 warning 统一成 operator-friendly 诊断信息。
- `guards.py`
  负责 live execution 二次确认和 repo-local secret 扫描。
- `preflight.py`
  负责不改 broker 状态的 readiness 检查。
- `state_tools.py`
  负责本地 state 的 doctor / prune / repair。
- `risk.py`
  负责 execution risk gate 和 kill switch 逻辑。
- `targets.py`
  负责 canonical `targets.json` 的 schema 与读写。
- `renderers/`
  负责表格、JSON、diff 和 operator summary 输出。
- `project_tools/`
  放置 signal-driven / target-driven / operator smoke harness，作为验证工装而不是策略框架。

## 设计取向

- 让模块名直接表达职责，避免平台化命名先行。
- live execution 输入边界严格收敛到统一的持仓清单 targets.json`。
- 本地 state 是幂等、恢复和 operator 操作的基础面。
- `orders` / `exceptions` / `order` 明确是 tracked-state 视图，不伪装成 broker 全量 blotter。

## 当前限制

- `--account` 已经是显式校验参数，但当前 LongPort real、`longport-paper` 和 Alpaca paper 都按单账户模式运行，不支持真实多账户切换。
- `resume-remaining` 当前只支持整数股剩余量；更复杂的碎股或算法单调度仍不在范围内。
- risk gate 里的 spread / participation / impact 依赖 broker 可提供的 market data；拿不到时会记录 `BYPASS`，而不是伪造指标。
- LongPort real broker 路径已经存在，但自动化端到端证据仍弱于 Alpaca paper smoke。
- `longport-paper` 默认优先 repo-local `.env` / `.env.local`，LongPort real 默认优先 `~/.config/qexec/longport-live.env`；这是为了把 paper smoke 重复性和 real secret 隔离同时保住。
