# Quant Execution Engine（量化执行引擎）

该项目是一个面向量化交易的执行模块，聚焦券商后台自动化下单、对账、恢复，以及必要的人工运维介入。  
当前默认支持长桥证券模拟盘与实盘、Alpaca 模拟盘验证路径，以及盈透模拟盘最小切片。  
为控制开发和维护复杂度，本项目不承担策略研究、回测或原始行情数据处理；如有需要，请与研究前台项目配合使用。

## 当前能力

- 查看当前可用的券商、风控和紧急停单配置
- 查询账户资金与持仓
- 拉取实时行情
- 基于 `targets.json` 生成调仓计划和差异预览
- 通过券商适配层执行 `submit / query / cancel / reconcile`
- 查看本地已跟踪订单、异常队列和单笔订单生命周期详情
- 对已跟踪订单执行 `cancel` / `cancel-all` / `retry` / `reprice` / `retry-stale`
- 对部分成交执行 `cancel-rest` / `resume-remaining` / `accept-partial`
- 运行正式的 `preflight` 预检查
- 维护本地状态：`state-doctor` / `state-prune` / `state-repair`
- 把调仓审计日志写入 `outputs/orders/*.jsonl`
- 把执行状态持久化到 `outputs/state/*.json`
- 提供面向信号、目标持仓和操作员的冒烟测试工装

## 当前成熟度与证据边界

按代码路径看，长桥证券的实盘，以及长桥证券、Alpaca 和盈透证券的模拟盘都已经接入券商后台的 submit/query/cancel/reconcile 语义，但它们的证据成熟度不同：

- `longport-paper` 依赖 `LONGPORT_ACCESS_TOKEN_TEST`；目前已经通过人工监督的模拟盘冒烟测试，跑通 `submit / query / reconcile / cancel` 最小闭环。
- LongPort 实盘账户已经通过人工监督只读方式验证 `config / preflight / account / quote`，并确认实盘保护和用户私有配置路由生效；`rebalance --execute` 仍按人工监督路径推进，成熟度判断以最小实盘冒烟、审计日志和可复查证据为准。
- Alpaca 当前按模拟盘验证路径使用，更适合作为便宜、直观、稳定的重复冒烟和回归基线。
- `ibkr-paper` 当前是本地 IB Gateway over TWS API 依赖型模拟盘后端，支持 `config / preflight / account / quote / rebalance --execute / cancel / reconcile` 的最小代码闭环；截至 2026-04-16，已有一次本地 operator-supervised WSL -> Windows Gateway evidence（`outputs/evidence/ibkr-paper-smoke.json`），证明 Gateway/account/reconcile 路径可达，但该次 AAPL 行情因 IBKR competing live session 返回 0，未产生 broker order；提交、成交、撤单证据仍需下一次有有效行情的 paper smoke 补齐。
- `orders` / `exceptions` / `order` 展示的是本地执行状态中已跟踪的订单。券商全量订单视图不在当前范围内。
- `--account` 当前只做显式标签解析和快速失败校验；LongPort 模拟盘、LongPort 实盘、Alpaca 模拟盘和 `ibkr-paper` 仍按单账户语义运行。

## 快速开始

安装依赖：

```bash
uv sync --group dev --extra cli
```

如果要启用 LongPort：

```bash
uv sync --group dev --extra cli --extra longport
```

如果要启用 Alpaca 模拟盘：

```bash
uv sync --group dev --extra cli --extra alpaca
```

如果要启用 IBKR 模拟盘：

```bash
uv sync --group dev --extra cli --extra ibkr
```

如果要同时安装全部券商依赖：

```bash
uv sync --group dev --extra cli --extra full
```

当前 CLI 不再假设默认 broker；请在 `config/config.yaml` 里显式设置 `broker.backend`，或在命令行传 `--broker`。

运行 CLI：

```bash
qexec --help
qexec config --broker longport-paper
qexec config --broker ibkr-paper
qexec preflight --broker longport-paper
qexec preflight --broker ibkr-paper
qexec account --broker longport-paper --format json
qexec account --broker ibkr-paper --format json
qexec quote AAPL 700.HK --broker longport-paper
qexec quote AAPL --broker ibkr-paper
qexec orders --broker longport-paper --status open
qexec exceptions --broker longport-paper --status failure
qexec order broker-order-id --broker longport-paper
qexec reconcile --broker longport-paper
qexec cancel broker-order-id --broker longport-paper
qexec cancel-rest broker-order-id --broker longport-paper
qexec resume-remaining broker-order-id --broker longport-paper
qexec accept-partial broker-order-id --broker longport-paper
qexec retry broker-order-id --broker longport-paper
qexec reprice broker-order-id --broker longport-paper --limit-price 9.50
qexec retry-stale --broker longport-paper --older-than-minutes 15
qexec state-doctor --broker longport-paper
qexec state-prune --broker longport-paper --older-than-days 30
qexec state-repair --broker longport-paper --clear-kill-switch --dedupe-fills
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute
qexec rebalance outputs/targets/2026-04-09.json --broker ibkr-paper --execute
# LongPort 实盘执行前，先按 docs/longport-real-smoke.md 完成操作手册
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --broker longport --execute
qexec rebalance outputs/targets/2026-04-09.json --broker alpaca-paper --execute
```

也可以直接通过模块入口运行：

```bash
PYTHONPATH=src python -m quant_execution_engine --help
```

`stockq` 仍保留为兼容别名；文档统一使用 `qexec`。

## 配置

LongPort 实盘至少需要：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

LongPort 模拟盘额外需要：

- `LONGPORT_ACCESS_TOKEN_TEST`

LongPort 实盘凭证的注入方式：

- 为了避免因 `.env` 被误提交，或整个项目被打包分享时把凭证一并带出，实盘路径会明确警告并拒绝从项目根目录 `.env*` / `.envrc*` 读取 `LONGPORT_ACCESS_TOKEN`
- 推荐在当前 shell 显式 `export`，或者从仓库外部的私有文件 `source`
- 推荐的用户级私有文件位置是 `~/.config/qexec/longport-live.env`
- `longport-paper` 默认优先读取仓库根目录 `.env` / `.env.local`；LongPort 实盘默认优先读取 `~/.config/qexec/longport-live.env`
- `qexec config --broker longport` / `qexec config --broker longport-paper` 会显示 App Key / Secret / Token / Region / Overnight 的命中来源
- 具体步骤见 [docs/longport-real-smoke.md](docs/longport-real-smoke.md)

LongPort 实盘的 `--execute` 还额外要求：

- `QEXEC_ENABLE_LIVE=1`
- 仓库根目录下的 `.env*` / `.envrc*` 不能包含 LongPort 实盘凭证，否则 CLI 会拒绝执行

Alpaca 模拟盘至少需要：

- `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

IBKR 模拟盘至少需要：

- 本地已启动并登录的 IB Gateway
- `IBKR_HOST`，默认 `127.0.0.1`
- `IBKR_PORT` 或 `IBKR_PORT_PAPER`，默认 `4002`
- `IBKR_CLIENT_ID`，默认 `1`
- 可选 `IBKR_ACCOUNT_ID`
- 可选 `IBKR_CONNECT_TIMEOUT_SECONDS`

说明：

- `ibkr-paper` 当前只支持 US equities 最小切片。
- 当前后端按本地 `IB Gateway + TWS API` 路线运行，不把 IBKR 当成纯云端 REST broker。
- 具体步骤见 [docs/ibkr-paper-smoke.md](docs/ibkr-paper-smoke.md)。

更多环境变量、本地 YAML、风控门禁和兼容项见：

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

测试边界应这样理解：

- 默认 `pytest` 证明的是快速行为测试通过。
- `e2e` 证明 CLI / 工装子进程的冒烟行为和输出边界。
- `integration` 证明跨模块生命周期行为，并在提供凭证或本地 runtime 时尝试 LongPort / IBKR 的 broker-backed 验证。
- 这些测试仍不能单独证明 LongPort 实盘交易能力已经被自动化完整跑实。
- `ibkr-paper` 的有效 broker order 证据仍依赖本地 Gateway 和有效行情下的 opt-in paper smoke。

## 冒烟测试工装

这些工装都放在核心代码之外：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/operator-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --execute --evidence-output outputs/evidence/ibkr-paper-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

它们的目标是驱动预演、模拟盘和人工监督验证。

如果你想系统化重复 `longport-paper` 的操作员失败场景冒烟，可先看 [docs/longport-paper-failure-smoke.md](docs/longport-paper-failure-smoke.md)。

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
- [docs/ibkr-paper-smoke.md](docs/ibkr-paper-smoke.md)
- [docs/longport-paper-failure-smoke.md](docs/longport-paper-failure-smoke.md)
- [docs/longport-real-smoke.md](docs/longport-real-smoke.md)
- [docs/testing.md](docs/testing.md)
- [docs/targets.md](docs/targets.md)
