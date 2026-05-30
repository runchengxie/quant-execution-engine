# Quant Execution Engine（量化执行引擎）

这是一个面向量化交易的独立执行引擎，主要负责券商后端的自动化下单、资金对账与异常恢复，同时提供必要的人工运维交互接口。

目前系统默认支持长桥证券的模拟盘与实盘、Alpaca 模拟盘，以及盈透证券模拟盘的核心美股交易。为了控制开发和维护的复杂度，本项目排除了策略研究、历史回测以及原始行情数据处理等环节，建议你将其与独立的研究前台项目搭配使用。

## 核心能力

* 账户与行情
  * 检查当前可用的券商接口、风控规则及紧急停单配置。
  * 查询账户的资金资产与具体持仓情况。
  * 获取实时的市场行情报价。

* 订单生成与执行
  * 读取标准化的 targets.json 目标持仓清单，自动生成调仓计划并提供执行前后的差异预览。
  * 借助统一的券商适配层，自动完成提交、查询、撤单与对账等完整的订单生命周期管理。

* 订单追踪与干预
  * 查询本地正在跟踪的订单列表、异常订单队列，以及单笔订单完整的流转细节。
  * 在条件允许的券商后端上，支持只读拉取券商原生的历史订单与成交记录，方便进行排障与审计。
  * 提供联合追踪视图，将本地记录与券商端历史合并至同一条时间线上以便复查。
  * 内置丰富的运维操作指令，包括单笔撤单、全部撤销、失败重试、改价重提，以及针对超时未成交订单的清理重试。
  * 针对部分成交的复杂场景提供专项处理指令，涵盖撤销剩余数量、继续执行剩余数量，以及直接接受当前部分成交结果。

* 运维与安全
  * 提供正式的执行前就绪性检查机制（preflight）。
  * 内置本地状态维护工具，支持执行状态的常规体检、历史数据清理与异常状态修复。

* 日志与审计验证
  * 自动汇总各券商适配器的代码覆盖情况与验证证据成熟度。
  * 支持根据运行编号打包本地的复查材料，并附带按订单维度聚合的追踪快照。
  * 规范化的本地文件输出，涵盖调仓审计日志、本地状态持久化文件，以及专项测试验证记录。
  * 配备独立的冒烟测试脚手架，方便操作员模拟量化信号与目标持仓进行全流程演练。

## 平台支持与功能成熟度

各项功能的最新支持情况请参阅 docs/current-capabilities.md 文件。简要总结如下：

* Alpaca 模拟盘属于低成本且高度稳定的环境，适合作为日常代码回归与冒烟测试的基础线。
* 长桥模拟盘已通过人工监督，保留了完整的提交、查询、对账与撤单验证证据。
* 长桥实盘已验证配置读取与实盘安全保护机制，实际的报单交易环节仍要求在人工监督下谨慎推进。
* 盈透模拟盘的接入强依赖本地运行的盈透网关，目前仅涵盖美股正股的基础交易，仍需补充有效行情下的完整流转证据。
* 命令行提供的各类订单和异常视图仅反映本地的追踪状态，它们独立于券商后端的全量历史订单簿。
* 券商原生订单与成交明细属于专门的只读查询指令，仅在具备此接口能力的后端上开放。
* 订单联合追踪指令能在获取历史记录失败时自动降级，照常展示本地的追踪明细。
* 账户指定参数仅用于配置标签的解析与有效性校验，当前暂未包含多账户自动路由功能。

## 快速开始

首先安装核心依赖：

```bash
uv sync --group dev --extra cli
```

根据你的实际需求追加安装对应的券商扩展包：

```bash
# 启用长桥证券
uv sync --group dev --extra cli --extra longport

# 启用 Alpaca 模拟盘
uv sync --group dev --extra cli --extra alpaca

# 启用盈透模拟盘
uv sync --group dev --extra cli --extra ibkr

# 一次性安装所有券商依赖
uv sync --group dev --extra cli --extra full
```

提示：当前命令行工具已取消默认券商的设定。请在 config/config.yaml 文件中明确配置 broker.backend 参数，或者在每次运行指令时主动附加 --broker 选项。

常用指令速览：

```bash
qexec --help

# 基础查询指令
qexec config --broker longport-paper
qexec preflight --broker ibkr-paper
qexec account --broker longport-paper --format json
qexec quote AAPL 700.HK --broker longport-paper

# 订单追踪与干预指令
qexec orders --broker longport-paper --status open
qexec exceptions --broker longport-paper --status failure
qexec order <broker-order-id> --broker longport-paper
qexec trace-order <broker-order-id> --broker longport-paper
qexec broker-orders --broker longport-paper --symbol AAPL
qexec broker-fills --broker longport-paper --order-id <broker-order-id>
qexec reconcile --broker longport-paper
qexec cancel <broker-order-id> --broker longport-paper
qexec cancel-all --broker longport-paper
qexec cancel-rest <broker-order-id> --broker longport-paper
qexec resume-remaining <broker-order-id> --broker longport-paper
qexec accept-partial <broker-order-id> --broker longport-paper
qexec reprice <broker-order-id> --broker longport-paper --limit-price 9.50
qexec retry-stale --broker longport-paper --older-than-minutes 15

# 本地状态维护指令
qexec state-doctor --broker longport-paper
qexec state-prune --broker longport-paper --older-than-days 30
qexec state-repair --broker longport-paper --clear-kill-switch --dedupe-fills

# 审计与复查指令
qexec evidence-maturity
qexec evidence-pack <run-id> --operator-note 测试输出已复查

# 调仓预演与正式执行
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute

# 长桥实盘执行（操作前务必查阅 docs/longport-real-smoke.md）
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --broker longport --execute
```

你同样可以通过标准的 Python 模块入口运行代码。本文档统一使用 qexec 指代主程序，系统同时兼容 stockq 别名：
```bash
PYTHONPATH=src python -m quant_execution_engine --help
```

## 配置说明

### 长桥证券配置

实盘环境必须提供的凭证：
* LONGPORT_APP_KEY
* LONGPORT_APP_SECRET
* LONGPORT_ACCESS_TOKEN

模拟盘环境额外要求的凭证：
* LONGPORT_ACCESS_TOKEN_TEST

实盘安全与环境隔离机制：
* 为了防止敏感凭证跟随代码提交或打包泄露，引擎会主动拦截并拒绝从项目根目录的 .env 相关文件中读取实盘令牌。
* 仓库内置的 .env.example 仅作模拟盘验证参考，内部剥离了实盘令牌的占位符。
* 推荐的实盘配置方案：在当前终端会话中直接导出环境变量，或者将凭证存储在代码仓库外部（推荐路径为 ~/.config/qexec/longport-live.env）并使用 source 命令加载。
* 差异化读取顺序：模拟盘优先读取项目根目录的配置文件，实盘则强制优先读取用户级私有文件。
* 实盘执行强制门禁：实盘下单指令必须附带 QEXEC_ENABLE_LIVE=1 环境变量。
* 运行 qexec config 命令可以清晰列出各项参数最终命中的来源路径，方便操作员排查当前生效的是测试配置还是私有配置。
* 更详尽的参数说明请查阅 docs/current-capabilities.md，实盘专门的操作规范请参考 docs/longport-real-smoke.md。

### Alpaca 模拟盘配置

必须提供的凭证：
* ALPACA_API_KEY 或者 APCA_API_KEY_ID
* ALPACA_SECRET_KEY 或者 APCA_API_SECRET_KEY
* 初次使用建议参考 docs/alpaca-paper-smoke.md 跑通基础流程。

### 盈透模拟盘配置

运行前置条件：
* 本地机器已启动并成功登录 IB Gateway 客户端。
* IBKR_HOST（默认指向 127.0.0.1）
* IBKR_PORT 或者 IBKR_PORT_PAPER（默认指向 4002）
* IBKR_CLIENT_ID（默认设定为 1）
* 可选参数包含 IBKR_ACCOUNT_ID 与 IBKR_CONNECT_TIMEOUT_SECONDS。
* 详细连通测试请参阅 docs/ibkr-paper-smoke.md。

完整的风控阈值与进阶本地 YAML 配置详见 docs/configuration.md。

## 测试与冒烟脚手架

运行基础与进阶测试：

```bash
# 运行极速的本地行为逻辑测试
uv run pytest

# 运行涉及跨模块与外部子进程调用的端到端测试
uv run pytest -m e2e

# 运行需要真实联网或依赖本地网关环境的集成测试
uv run pytest -m integration
```
备注：自动化测试仅负责校验程序的行为逻辑。有关真实交易网关的可靠性证明，请依靠人工监督下的实盘冒烟测试以及对应留存的审计数据。各接口的验证成熟度均记录在 docs/current-capabilities.md 文件中。

当前默认测试可以作为本地行为回归入口，但它不等同于完整质量门控。维护者还应按需运行：

```bash
uv run python -m compileall -q src tests project_tools
uv run ruff check .
uv run mypy src tests project_tools
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

其中 Ruff、mypy 目前仍处于维护债收敛阶段，可能暴露既有问题。默认 `pytest` 通过只说明快速行为测试通过，不代表格式、lint、类型检查和覆盖率门槛全部达标。

使用冒烟测试脚手架：

仓库内附带了一组脱离核心业务流的独立脚本，专门用于生成测试数据和模拟人工流转：

```bash
# 生成标准格式的测试信号与目标持仓文件
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario carry-over --print-json

# 模拟日常量化运维的全流程作业（涵盖预检、执行、留存档案及事后清理）
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

## 输入与输出规范

引擎严格要求调仓指令采用如下格式的标准 JSON 文件：

```json
{
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

相应的输出目录结构约定如下：
* 调仓流水审计日志存放于 outputs/orders/*.jsonl
* 本地运行状态持久化数据存放于 outputs/state/*.json
* 冒烟验证记录存档于 outputs/evidence/*.json
* 自动打包的复查材料汇总于 outputs/evidence-bundles/*

## 详细文档目录

获取特定流程的深度设计说明与操作手册：

* [架构设计](docs/architecture.md)
* [当前能力与成熟度](docs/current-capabilities.md)
* [命令行接口说明](docs/cli.md)
* [环境与配置文件详解](docs/configuration.md)
* [目标持仓文件格式规范](docs/targets.md)
* [执行底座核心逻辑](docs/execution-foundation.md)
* [项目开发功能清单](docs/execution-checklist.md)
* [自动化测试指南](docs/testing.md)
* 专项运行手册：
  * [Alpaca 模拟盘冒烟演练](docs/alpaca-paper-smoke.md)
  * [盈透模拟盘冒烟演练](docs/ibkr-paper-smoke.md)
  * [长桥模拟盘失败场景演练](docs/longport-paper-failure-smoke.md)
  * [长桥实盘谨慎冒烟演练](docs/longport-real-smoke.md)