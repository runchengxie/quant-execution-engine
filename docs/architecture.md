# Architecture

## 定位

`quant_execution_engine` 是一个 execution-only 包。

它负责：

- broker 凭证与连接封装
- 账户快照与行情抓取
- 调仓计划生成与 diff 预览
- dry-run / live-mode 调仓流程
- 审计输出与终端渲染

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
  broker/
    __init__.py
    _stubs.py
    longport.py
  renderers/
    __init__.py
    diff.py
    jsonout.py
    table.py
```

## 分层说明

- `cli.py`
  负责参数解析、命令分发和错误码收口。
- `broker/longport.py`
  负责 LongPort SDK 封装、环境变量兼容和基础 broker 操作。
- `account.py`
  负责账户快照与行情查询的业务组装。
- `rebalance.py`
  负责目标仓位计算、订单规划、执行和审计日志。
- `targets.py`
  负责 canonical `targets.json` 的 schema 与读写。
- `renderers/`
  负责表格、JSON、diff 输出。

## 设计取向

- 不保留 monolith 时代的 `shared/`、`app/commands/`、`contracts/` 套娃层级。
- 尽量让模块名直接表达职责。
- live execution 的输入边界严格收敛到 schema-v2 JSON。

## 当前限制

- `cli.py` 的 `rebalance --account` 目前只做兼容和日志记录，不会切换实际 broker 账户。
- `broker/longport.py` 的 live-mode `place_order()` 分支当前仍返回模拟 `order_id`，还没有真正提交 LongPort 订单。
