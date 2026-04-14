# Architecture

## 定位

`quant_execution_engine` 是一个 execution-only 包。

它负责：

- broker adapter、能力矩阵与凭证封装
- 账户快照与行情抓取
- 调仓计划生成与 diff 预览
- dry-run / live / paper 调仓流程
- order intent / broker order / fill event / reconcile 生命周期
- execution risk gate 与 kill switch
- 审计输出、状态持久化与终端渲染

它不再负责：

- research 产出生成
- AI 选股
- 回测
- 数据导入

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
  risk.py
  broker/
    __init__.py
    base.py
    factory.py
    alpaca.py
    _stubs.py
    longport.py
  renderers/
    __init__.py
    diff.py
    jsonout.py
    table.py
project_tools/
  smoke_signal_harness.py
  smoke_target_harness.py
```

## 分层说明

- `cli.py`
  负责参数解析、broker/backend 选择、命令分发和错误码收口。
- `broker/base.py` / `broker/factory.py`
  定义 broker lifecycle 契约、capability matrix 和 backend 选择逻辑。
- `broker/longport.py` / `broker/alpaca.py`
  分别负责 LongPort live 和 Alpaca paper 的 adapter 实现。
- `account.py`
  负责通过 adapter 获取账户快照与行情查询。
- `rebalance.py`
  负责目标仓位计算、订单规划、执行入口和审计日志。
- `execution.py`
  负责 order intent、parent/child order、状态持久化、幂等提交和 reconcile 协调。
- `risk.py`
  负责 execution risk gate 和 kill switch 逻辑。
- `targets.py`
  负责 canonical `targets.json` 的 schema 与读写。
- `renderers/`
  负责表格、JSON、diff 输出。
- `project_tools/`
  放置 signal-driven / target-driven smoke harness，作为验证工装而不是策略框架。

## 设计取向

- 不保留 monolith 时代的 `shared/`、`app/commands/`、`contracts/` 套娃层级。
- 尽量让模块名直接表达职责。
- live execution 的输入边界严格收敛到 schema-v2 JSON。
- 不把回测、数据中心、dashboard 或部署编排并回核心包。

## 当前限制

- `--account` 已经是显式校验参数，但当前 LongPort 与 Alpaca paper 都按单账户模式运行，不支持多账户切换。
- risk gate 里的 spread / participation / impact 依赖 broker 可提供的 market data；拿不到时会记录 `BYPASS` 决策，而不是伪造指标。
- parent/child order 目前以“单 child + 剩余量跟踪”为主，还没有做完整的 TWAP / POV 调度器。
