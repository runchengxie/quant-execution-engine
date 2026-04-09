<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Execution Engine](#execution-engine)
  - [安装](#%E5%AE%89%E8%A3%85)
  - [CLI](#cli)
  - [Targets JSON](#targets-json)
  - [配置文件](#%E9%85%8D%E7%BD%AE%E6%96%87%E4%BB%B6)
  - [测试](#%E6%B5%8B%E8%AF%95)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Execution Engine

这个仓库现在只承载交易执行侧能力，不再包含 research、AI 选股、数据导入或回测流程。

上游 `research-core` 负责生成 canonical `targets.json`，本仓库负责：

- 查看 LongPort 配置
- 查看账户资金和持仓
- 拉取实时行情
- 基于 schema-v2 `targets.json` 生成调仓计划并执行

## 安装

```bash
uv sync
```

需要配置 LongPort 环境变量：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`
- `LONGPORT_REGION`，可选，默认 `hk`
- `LONGPORT_ENABLE_OVERNIGHT`，可选
- `LONGPORT_MAX_NOTIONAL_PER_ORDER`，可选
- `LONGPORT_MAX_QTY_PER_ORDER`，可选
- `LONGPORT_TRADING_WINDOW_START`，可选
- `LONGPORT_TRADING_WINDOW_END`，可选

## CLI

```bash
stockq lb-config
stockq lb-account --format json
stockq lb-quote AAPL 700.HK
stockq lb-rebalance outputs/targets/2025-09-05.json
stockq lb-rebalance outputs/targets/2025-09-05.json --execute
```

`lb-rebalance` 只接受 canonical schema-v2 `targets.json`，不再接受旧的 Excel 或 ticker-list 输入。

## Targets JSON

最小示例：

```json
{
  "schema_version": 2,
  "asof": "2026-04-09",
  "source": "research-core",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_weight": 0.5
    },
    {
      "symbol": "700",
      "market": "HK",
      "target_weight": 0.5
    }
  ]
}
```

每个 target 必须二选一：

- `target_weight`
- `target_quantity`

## 配置文件

复制 [config/template.yaml](/home/richard/code/quant-execution-engine/config/template.yaml) 到 `config/config.yaml` 后按需修改。

当前模板只保留 execution 侧会读取的配置：

- `fees`
- `fractional_preview`
- `fx`

## 测试

```bash
pytest
```
