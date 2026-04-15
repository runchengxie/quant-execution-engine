# Quant Execution Engine

execution-only 仓库，聚焦 broker-backed 下单、对账、恢复和 operator 运维，不承担 research / backtest / data ingestion。

当前默认支持 LongPort real broker，并提供 `longport-paper` 与 `alpaca-paper` 两条 paper 验证路径。

## 当前能力

- 查看有效 broker / risk / kill-switch 配置
- 查询账户资金与持仓
- 拉取实时行情
- 基于 canonical schema-v2 `targets.json` 生成调仓计划与 diff 预览
- 通过 broker adapter 执行 `submit / query / cancel / reconcile`
- 查看本地 tracked orders / exception queue / 单笔生命周期详情
- 对部分成交执行 `cancel-rest` / `resume-remaining` / `accept-partial`
- 运行正式 `preflight` 检查
- 维护本地状态：`state-doctor` / `state-prune` / `state-repair`
- 写出调仓审计日志到 `outputs/orders/*.jsonl`
- 持久化执行状态到 `outputs/state/*.json`
- 提供 signal / target / operator smoke harness

## 成熟度与证明边界

- LongPort real broker、`longport-paper` 和 Alpaca paper 都已经走 broker-backed `submit / query / cancel / reconcile` 代码路径。
- `longport-paper` 需要 `LONGPORT_ACCESS_TOKEN_TEST`；Alpaca paper 仍是当前更成熟的重复 smoke 环境。
- LongPort real broker 路径已经存在，但自动化端到端证据仍然弱于 Alpaca paper。对 real broker 的成熟度判断，应该以 operator-supervised smoke 和记载下来的证据链为准，而不是只看“代码路径存在”。
- `orders` / `exceptions` / `order` 展示的是本地 execution state 中已跟踪的订单，不是 broker 全量订单视图。
- `--account` 当前是显式 label 解析与 fail-fast 校验；LongPort 和 Alpaca paper 仍按单账户语义运行。

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
qexec preflight
qexec preflight --broker longport-paper
qexec account --format json
qexec quote AAPL 700.HK
qexec orders --status open
qexec exceptions --status failure
qexec order broker-order-id
qexec reconcile
qexec cancel broker-order-id
qexec cancel-rest broker-order-id
qexec resume-remaining broker-order-id
qexec accept-partial broker-order-id
qexec retry broker-order-id
qexec reprice broker-order-id --limit-price 9.50
qexec retry-stale --older-than-minutes 15
qexec state-doctor
qexec state-prune --older-than-days 30
qexec state-repair --clear-kill-switch --dedupe-fills
qexec rebalance outputs/targets/2026-04-09.json
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --execute
qexec rebalance outputs/targets/2026-04-09.json --broker alpaca-paper --execute
```

也可以直接用模块入口：

```bash
PYTHONPATH=src python -m quant_execution_engine --help
```

`stockq` 仍保留为兼容别名，但文档统一使用 `qexec`。

## 配置

LongPort live 至少需要：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

LongPort paper 额外需要：

- `LONGPORT_ACCESS_TOKEN_TEST`

LongPort real broker 的 `--execute` 额外要求：

- `QEXEC_ENABLE_LIVE=1`
- repo 根目录下的 `.env*` / `.envrc*` 不得包含 LongPort live 凭证；否则 CLI 会拒绝执行

Alpaca paper 至少需要：

- `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

更多环境变量、本地 YAML、risk gate 和兼容项见：

- [docs/configuration.md](docs/configuration.md)

## 测试

默认入口只跑快速测试：

```bash
uv run pytest
```

按需运行其他层级：

```bash
uv run pytest -m e2e
uv run pytest -m integration
```

测试边界要这样理解：

- 默认 `pytest` 证明的是快速行为测试通过。
- `e2e` 证明 CLI / harness 的 subprocess smoke 行为和输出边界。
- `integration` 证明跨模块 lifecycle 行为，并在提供凭证时尝试 LongPort quote 级别验证。
- 这些测试还不能单独证明 LongPort real broker 的完整 live execution 已经被自动化跑实。

## Smoke Harness

这些工装都放在 core package 外：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/operator-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
```

它们的目标是驱动 dry-run / paper / operator-supervised 验证，而不是提供策略层。

## 输入与输出

持仓清单最小示例：

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

- 调仓审计日志：`outputs/orders/*.jsonl`
- 执行状态持久化：`outputs/state/*.json`

## 文档

- [docs/architecture.md](docs/architecture.md)
- [docs/cli.md](docs/cli.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/execution-checklist.md](docs/execution-checklist.md)
- [docs/execution-foundation.md](docs/execution-foundation.md)
- [docs/testing.md](docs/testing.md)
- [docs/targets.md](docs/targets.md)
