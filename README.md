# Quant Execution Engine

面向 execution-only 场景的轻量执行引擎仓库，当前默认支持 LongPort，并提供 Alpaca paper 适配层用于低成本验证。

这个 repo 当前保留的能力：

- 查看有效 broker / risk / kill-switch 配置
- 查询账户资金与持仓
- 拉取实时行情
- 查看本地跟踪的 broker orders
- 基于 canonical `targets.json` 生成调仓计划与 diff 预览
- 通过 broker adapter 执行 `submit / query / cancel / reconcile`
- 在 live / paper 路径上做轻量 execution risk gate
- 写出调仓审计日志到 `outputs/orders/*.jsonl`
- 持久化执行状态到 `outputs/state/*.json`
- 提供外置 smoke harness 生成 signal-driven / target-driven 测试输入

research、AI、回测、数据导入相关内容已经从这个仓库移除。

当前实现限制：

- LongPort 仍按单账户模式使用；`--account` 目前会做显式校验，不支持的 label 会 fail fast，而不会静默切账户。
- Alpaca paper 适配层依赖可选的 `alpaca-py` 安装和 Alpaca 环境变量。
- smoke harness 是验证工装，不是策略框架；repo 仍然不承担 research / backtest 职责。

## 快速开始

安装依赖：

```bash
uv sync --group dev --extra cli
```

如果要启用 Alpaca paper：

```bash
uv sync --group dev --extra cli --extra alpaca
```

运行 CLI：

```bash
qexec --help
qexec config
qexec account --format json
qexec quote AAPL 700.HK
qexec orders
qexec order broker-order-id
qexec reconcile
qexec cancel broker-order-id
qexec cancel-all
qexec retry broker-order-id
qexec rebalance outputs/targets/2026-04-09.json
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --execute
qexec rebalance outputs/targets/2026-04-09.json --broker alpaca-paper --execute
```

也可以直接用模块入口：

```bash
PYTHONPATH=src python -m quant_execution_engine --help
```

`stockq` 仍保留为兼容别名，但后续文档统一使用 `qexec`。

## 配置

LongPort live 至少需要：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

LongPort real broker 的 `--execute` 额外要求：

- `QEXEC_ENABLE_LIVE=1`
- repo 根目录下的 `.env*` / `.envrc*` 不得包含 LongPort live 凭证；否则 CLI 会拒绝执行，避免把 real secret 留在仓库本地文件里

Alpaca paper 至少需要：

- `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

可选环境变量、本地 YAML 配置和 FX 折算见：

- [docs/configuration.md](docs/configuration.md)

`config/template.yaml` 提供了 execution-only 的最小本地配置模板，包含 broker backend、risk gate 和 kill switch 样例；`.env.example` 提供了最小环境变量示例。

## 测试

默认测试只跑快速单元测试：

```bash
uv run pytest
```

按需运行其他测试层级：

```bash
uv run pytest -m e2e
uv run pytest -m integration
```

如果你想看覆盖率，可以显式开启，而不是让默认测试强制失败：

```bash
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

## 文档

- [docs/architecture.md](docs/architecture.md)
- [docs/cli.md](docs/cli.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/execution-foundation.md](docs/execution-foundation.md)
- [docs/testing.md](docs/testing.md)
- [docs/targets.md](docs/targets.md)

## 测试运行

这些工装都放在 core package 外：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json
PYTHONPATH=src python project_tools/smoke_signal_harness.py --broker alpaca-paper --execute
```

它们的目标是驱动模拟盘交易 / dry-run 行为验证，而不是提供正式策略层。

## 输入约定

执行引擎只接受 canonical schema-v2 `targets.json`。

- 不再接受 Excel
- 不再接受 legacy ticker-list 作为 live execution 输入

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

## 输出约定

- 调仓审计日志：`outputs/orders/*.jsonl`
- 执行状态持久化：`outputs/state/*.json`
