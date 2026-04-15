# Quant Execution Engine

该项目为量化投资执行模块，聚焦券商后台自动化下单、对账、恢复和必要的人工介入运维\
当前默认支持长桥 LongPort 模拟盘/实盘，以及 Alpaca 模拟盘验证路径\
为降低开发维护复杂度，该项目不承担策略研究 / 回测 / 股票原始数据处理，如有需要请结合研究前台项目使用\

## 当前能力

- 查看有效券商 / 风控 / 紧急关停配置
- 查询账户资金与持仓
- 拉取实时行情
- 基于 `targets.json` 生成调仓计划与 diff 预览
- 通过券商适应层来执行 `submit / query / cancel / reconcile`
- 查看查看本地跟踪订单、异常队列和单笔订单生命周期详情
- 对部分成交执行 `cancel-rest` / `resume-remaining` / `accept-partial`
- 运行正式预检查（`preflight`）检查
- 维护本地状态：`state-doctor` / `state-prune` / `state-repair`
- 写出调仓审计日志到 `outputs/orders/*.jsonl`
- 持久化执行状态到 `outputs/state/*.json`
- 提供面向 signal / target / operator 的冒烟测试工装

## 成熟度与证明边界

- 当前已经落地 broker-backed `submit / query / cancel / reconcile` 代码路径的，是长桥 LongPort real、`longport-paper` 和 `alpaca-paper`。
- `longport-paper` 依赖 `LONGPORT_ACCESS_TOKEN_TEST`；当前已经通过 operator-supervised paper smoke 跑通过 `submit / query / reconcile / cancel` 最小闭环。
- 长桥 LongPort 实盘账户已通过人工监督只读模式验证跑通 `config / preflight / account / quote`，并确认 live guard 与用户私有配置路由生效。
- 长桥 LongPort 的 `rebalance --execute` 仍不应被视为默认自动化已经跑实的能力；成熟度判断仍要看最小实盘冒烟测试、审计日志和可复查信息。
- Alpaca 当前按模拟盘验证路径使用，仍然适合作为更直观、更稳定的重复冒烟 / 回归测试基线。
- `orders` / `exceptions` / `order` 展示的是本地执行状态中已跟踪的订单，暂不反映券商全量订单视图。
- `--account` 当前是显式 label 解析与 fail-fast 校验，长桥 LongPort 模拟盘 / 实盘 和 Alpaca 模拟盘都仍按单账户语义运行。

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
# LongPort real execute 前先按 docs/longport-real-smoke.md 完成 playbook
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

LongPort live token 的注入方式：

- 为了防止git管理不善或者把完整项目打包分享给他人时忘记排除.env文件，该项目在实盘运行时会明确警告并拒绝通过项目根目录 `.env*` / `.envrc*`来读取`LONGPORT_ACCESS_TOKEN`
- 推荐在当前 shell 显式 `export`，或从项目外外部的私有文件 `source`
- 推荐的用户级私有文件位置是 `~/.config/qexec/longport-live.env`
- `longport-paper` 默认优先读取 repo 根目录 `.env` / `.env.local`；`longport` real 默认优先读取 `~/.config/qexec/longport-live.env`
- `qexec config --broker longport` / `qexec config --broker longport-paper` 会显示 App Key / Secret / Token / Region / Overnight 的命中来源
- 具体步骤见 [docs/longport-real-smoke.md](docs/longport-real-smoke.md)

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
- `e2e` 证明 CLI / harness 的子过程冒烟测试行为和输出边界。
- `integration` 证明跨模块生命周期行为，并在提供凭证时尝试长桥 LongPort 报价级别验证。
- 这些测试还不能单独证明长桥 LongPort 实盘交易功能的完整执行能力已经被自动化跑实。

## 冒烟测试工装

这些工装都放在核心代码外：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/operator-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

它们的目标是驱动 dry-run / paper / 人工监督验证。

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
- [docs/longport-real-smoke.md](docs/longport-real-smoke.md)
- [docs/testing.md](docs/testing.md)
- [docs/targets.md](docs/targets.md)
