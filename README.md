# Quant Execution Engine（量化执行引擎）

这是一个面向量化交易的独立执行引擎，专注于券商后端的自动化下单、资金对账、异常恢复，并提供必要的人工干预（运维）接口。

目前已默认支持长桥证券（LongPort）的模拟盘与实盘、Alpaca 模拟盘，以及盈透证券（IBKR）模拟盘的核心美股交易。为控制开发和维护的复杂度，本项目不包含策略研究、回测或原始行情数据处理模块；建议将其与你的“研究前台”项目配合使用。

## 核心能力

*   账户与行情
    *   查看当前可用的券商、风控及紧急停单配置。
    *   查询账户资金与持仓情况。
    *   获取实时市场行情。
*   订单生成与执行
    *   基于标准化的 `targets.json` 目标持仓清单生成调仓计划与差异预览。
    *   通过统一的券商适配层执行完整的订单生命周期：提交、查询、撤单与对账（`submit / query / cancel / reconcile`）。
*   订单追踪与干预
    *   查看本地已跟踪订单、异常队列，以及单笔订单的完整生命周期详情。
    *   丰富的手动操作指令：撤单（`cancel`）、全部撤销（`cancel-all`）、失败重试（`retry`）、改价重提（`reprice`）、重试过旧未成交订单（`retry-stale`）。
    *   部分成交（Partial Fill）处理：撤销剩余（`cancel-rest`）、继续执行剩余数量（`resume-remaining`）、接受部分成交结果（`accept-partial`）。
*   运维与安全
    *   运行正式的执行前预检查（`preflight`）。
    *   本地状态的体检、清理和修复（`state-doctor` / `state-prune` / `state-repair`）。
*   日志与审计验证
    *   查看各券商适配器的代码路径与验证成熟度（`evidence-maturity`）。
    *   按审计 `run_id` 打包本地复查证据（`evidence-pack`）。
    *   结构化输出：调仓审计日志（`outputs/orders/*.jsonl`）、本地状态持久化（`outputs/state/*.json`）、测试验证记录（`outputs/evidence/*.json` 及 `outputs/evidence-bundles/*`）。
    *   内置面向量化信号、目标持仓和操作员的冒烟测试脚手架（Harness）。

## 平台支持与功能成熟度

从代码实现来看，长桥实盘，以及长桥、Alpaca、盈透的模拟盘均已跑通了基础的订单生命周期闭环，但各自的自动化验证（证据）成熟度有所不同：

*   Alpaca 模拟盘：作为低成本、稳定且直观的基线测试环境，非常适合用于日常的回归测试和重复冒烟测试。
*   长桥（LongPort）模拟盘：依赖 `LONGPORT_ACCESS_TOKEN_TEST`，目前已通过人工监督的冒烟测试，跑通了完整的业务闭环。
*   长桥（LongPort）实盘：已通过只读模式验证了配置、预检查、账户和行情功能，并确认了实盘保护机制及私有配置路由生效。但实盘下单（`rebalance --execute`）目前仍处于人工监督阶段，最终成熟度以实际交易的审计日志及可复查证据为准。
*   盈透（IBKR）模拟盘：基于本地 `IB Gateway` + `TWS API` 运行，支持代码最小闭环（目前暂仅支持美股交易）。
*   *注 1*：CLI 工具中的订单/异常视图仅展示本地执行状态中已跟踪的订单，并非券商后台的全量订单簿。
*   *注 2*：`--account` 参数目前仅用于标签解析和快速失败校验，暂不支持真实的多账户路由（各券商均按单账户语义运行）。

## 快速开始

安装核心依赖：

```bash
uv sync --group dev --extra cli
```

按需安装券商扩展包：

```bash
# 启用长桥（LongPort）
uv sync --group dev --extra cli --extra longport

# 启用 Alpaca 模拟盘
uv sync --group dev --extra cli --extra alpaca

# 启用 IBKR 模拟盘
uv sync --group dev --extra cli --extra ibkr

# 安装全部券商依赖
uv sync --group dev --extra cli --extra full
```

*提示：当前 CLI 不再预设默认券商，请在 `config/config.yaml` 中显式设置 `broker.backend`，或在执行命令时通过 `--broker` 参数指定。*

常用 CLI 命令速览：

```bash
qexec --help

# 基础查询
qexec config --broker longport-paper
qexec preflight --broker ibkr-paper
qexec account --broker longport-paper --format json
qexec quote AAPL 700.HK --broker longport-paper

# 订单追踪与干预
qexec orders --broker longport-paper --status open
qexec exceptions --broker longport-paper --status failure
qexec order <broker-order-id> --broker longport-paper
qexec reconcile --broker longport-paper
qexec cancel <broker-order-id> --broker longport-paper
qexec cancel-rest <broker-order-id> --broker longport-paper
qexec accept-partial <broker-order-id> --broker longport-paper
qexec reprice <broker-order-id> --broker longport-paper --limit-price 9.50
qexec retry-stale --broker longport-paper --older-than-minutes 15

# 本地状态维护
qexec state-doctor --broker longport-paper
qexec state-prune --broker longport-paper --older-than-days 30
qexec state-repair --broker longport-paper --clear-kill-switch --dedupe-fills

# 审计与复查
qexec evidence-maturity
qexec evidence-pack <run-id> --operator-note "终端输出已复查"

# 执行调仓 (Dry-run 与 Execute)
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute

# 长桥实盘执行（操作前请务必先阅读 docs/longport-real-smoke.md）
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --broker longport --execute
```

你也可以直接通过模块入口运行（文档中统称为 `qexec`，兼容别名为 `stockq`）：
```bash
PYTHONPATH=src python -m quant_execution_engine --help
```

## 配置说明

### 长桥（LongPort）配置

实盘必备凭证：
*   `LONGPORT_APP_KEY`
*   `LONGPORT_APP_SECRET`
*   `LONGPORT_ACCESS_TOKEN`

模拟盘额外要求：
*   `LONGPORT_ACCESS_TOKEN_TEST`

实盘安全与配置隔离设计：
*   为防止 `.env` 文件被误提交或随项目打包泄露，实盘路径会强拦截并拒绝从项目根目录的 `.env*` / `.envrc*` 读取实盘 Token。
*   实盘推荐配置方式：在当前 shell 中显式 `export`，或将私有凭证存放在项目外部（推荐路径：`~/.config/qexec/longport-live.env`），并使用 `source` 加载。
*   读取优先级：模拟盘（`longport-paper`）优先读取项目根目录的 `.env`；实盘（`longport`）优先读取用户级私有文件 `~/.config/qexec/longport-live.env`。
*   实盘执行门禁：实盘下单（`--execute`）必须设置环境变量 `QEXEC_ENABLE_LIVE=1`，且项目根目录下严禁出现实盘凭证。
*   使用 `qexec config --broker longport` 可查看各项配置的最终命中来源。
*   详情请参阅 [docs/longport-real-smoke.md](docs/longport-real-smoke.md)。

### Alpaca 模拟盘配置

必备凭证：
*   `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
*   `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`
*   建议先参考 [docs/alpaca-paper-smoke.md](docs/alpaca-paper-smoke.md) 跑通基础流程。

### IBKR 模拟盘配置

必备条件：
*   本地已启动并成功登录的 IB Gateway
*   `IBKR_HOST`（默认 `127.0.0.1`）
*   `IBKR_PORT` 或 `IBKR_PORT_PAPER`（默认 `4002`）
*   `IBKR_CLIENT_ID`（默认 `1`）
*   可选：`IBKR_ACCOUNT_ID`, `IBKR_CONNECT_TIMEOUT_SECONDS`
*   详情请参阅 [docs/ibkr-paper-smoke.md](docs/ibkr-paper-smoke.md)。

更多环境变量、本地 YAML 配置及风控参数，请查阅 [docs/configuration.md](docs/configuration.md)。

## 测试与冒烟脚手架

单元与集成测试：

```bash
# 仅运行快速的行为单元测试
uv run pytest

# 运行包含外部命令调用的端到端测试
uv run pytest -m e2e

# 运行跨模块及依赖外部运行时的集成测试
uv run pytest -m integration
```
*注：自动化测试仅覆盖行为逻辑，实盘交易的稳定性证明仍以人工监督下的冒烟测试及留存的审计数据为准。*

冒烟测试脚手架 (Smoke Harnesses)：

本项目提供了一组独立于核心代码的脚本，用于预演、测试和人工监督验证：

```bash
# 生成测试信号与目标持仓
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json

# 模拟操作员的完整作业流冒烟测试（支持预检、执行、留存证据及清理）
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

## 输入与输出规范

输入：持仓清单 (`targets.json`) 最小示例

引擎仅接受以下标准 JSON 作为调仓输入：

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

输出目录约定：
*   调仓审计日志：`outputs/orders/*.jsonl`
*   本地执行状态持久化：`outputs/state/*.json`
*   冒烟测试证据：`outputs/evidence/*.json`
*   审计打包结果：`outputs/evidence-bundles/*`

## 详细文档目录

深入了解引擎设计与特定流程操作手册：

*   [架构设计 (Architecture)](docs/architecture.md)
*   [CLI 命令参考 (CLI)](docs/cli.md)
*   [配置文件说明 (Configuration)](docs/configuration.md)
*   [目标文件格式 (Targets)](docs/targets.md)
*   [执行底座说明 (Execution Foundation)](docs/execution-foundation.md)
*   [项目功能清单 (Checklist)](docs/execution-checklist.md)
*   [测试指南 (Testing)](docs/testing.md)
*   专项操作手册：
    *   [Alpaca 模拟盘冒烟测试](docs/alpaca-paper-smoke.md)
    *   [IBKR 模拟盘冒烟测试](docs/ibkr-paper-smoke.md)
    *   [长桥模拟盘失败场景演练](docs/longport-paper-failure-smoke.md)
    *   [长桥实盘冒烟测试](docs/longport-real-smoke.md)