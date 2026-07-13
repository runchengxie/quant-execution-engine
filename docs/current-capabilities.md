# 当前功能与能力边界

本代码仓库是一个纯粹的面向量化交易的执行引擎。它涵盖了券商适配器、账户与行情读取、调仓计划生成、订单提交、本地执行状态维护、状态对账、异常恢复命令、审计日志以及冒烟测试证据留存等功能。本项目暂不支持策略研究、历史回测、原始数据导入、因子计算流水线、跨券商的多账户统一路由中台服务。

## 券商支持矩阵

| 券商后端 | 当前运行路径 | 运行环境要求 | 证据成熟度 | 当前缺口 |
| --- | --- | --- | --- | --- |
| Alpaca 模拟盘（`alpaca-paper`，兼容别名 `alpaca`） | 纯模拟盘适配器，支持提交、查询、撤单与对账链路。 | 环境变量 `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`，以及 `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`。 | 作为稳定且低成本的模拟盘基线，用于反复运行回归与冒烟测试。默认测试使用伪造数据，无需网络连接。 | 暂不支持 Alpaca 实盘路径。 |
| 长桥模拟盘（`longport-paper`） | 长桥模拟盘后端，支持真实的券商端提交、查询、撤单与对账链路。 | 需配置 `LONGPORT_APP_KEY`、`LONGPORT_APP_SECRET` 以及 `LONGPORT_ACCESS_TOKEN_TEST`。允许在项目本地的 `.env` 和 `.env.local` 文件中配置模拟盘凭证。 | 人工监督下的模拟盘冒烟测试已覆盖基础的提交、查询、对账与撤单流程。 | 失败场景的测试证据仍需持续补充。 |
| 长桥实盘（`longport`） | 长桥实盘后端，在实盘保护机制下提供真实的券商端读取与执行链路。 | 需配置 `LONGPORT_APP_KEY`、`LONGPORT_APP_SECRET`、`LONGPORT_ACCESS_TOKEN`，且在执行实盘下单（`--execute`）时需要显式设置环境变量 `QEXEC_ENABLE_LIVE=1`。实盘凭证必须来自当前进程环境或用户私有文件 `~/.config/qexec/longport-live.env`，严禁存放在项目本地的 `.env*` 或 `.envrc*` 文件中。 | 人工监督下的只读检查已验证配置加载、预检、账户查询、行情获取、私有实盘配置路由以及实盘保护机制的表现。 | 完整的实盘提交、查询、撤单与对账证据目前仍弱于模拟盘冒烟测试，必须继续在人工监督下谨慎推进。 |
| 盈透模拟盘（`ibkr-paper`） | 依赖本地运行的盈透网关的模拟盘后端，目前仅支持美股正股的最小切片。 | 已启动并成功登录的本地盈透网关；环境变量 `IBKR_HOST`、`IBKR_PORT` 或 `IBKR_PORT_PAPER`、`IBKR_CLIENT_ID`，以及可选的 `IBKR_ACCOUNT_ID`。 | 无报单级别的证据已证明网关连接、账户、行情、调仓、对账与全部撤单链路的连通性。 | 仍缺乏在有效市场行情下，真实的券商端报单、撤单与成交证据。 |
| A 股 / CN 文件契约（`local-dry-run`） | `targets.json` 可解析 `market: CN` 目标，适合作为中国大陆市场研究到执行的 dry-run 合约验收。`local-dry-run` 后端只提供离线现金、合成报价和手数规则，用于无网络文件契约预演。 | 由 `cstree export-targets` 生成的 `.SH`、`.SZ`、`.BJ` 标的应保留交易所后缀；`.XSHG`、`.XSHE` 会标准化为 `.SH`、`.SZ`。估值前必须提供 `FX_CNY_USD` 或 `fx.to_usd.CNY`。不带 `--execute` 的 `qexec rebalance` 不会提交订单。 | 当前完成文件契约级验收；中国大陆市场真实报单能力需要另行提供券商证据。 | 当前券商后端没有宣称中国大陆市场真实报单能力；真实账户权限、券商接口、港股通或 A 股账户能力必须单独验证。 |

## 共享执行语义

> 新增的 durable execution journal 与类型化 transport 当前是 additive API。现有 broker
> adapter 已可通过机械 adapter 进入新边界，但 `rebalance`、v1 状态命令和默认 CLI 尚未切换。
> 这不能被解读为现有实盘路径已经完成 event-journal 迁移；迁移边界见
> `durable-execution-journal.md` 和 `execution-transport.md`。

vn.py Gateway/OMS bridge 当前也是 additive、experimental transport：

- 依赖 `vnpy` optional extra，默认 `SHADOW`，未接入 `qexec rebalance`；
- 本仓没有捆绑具体 vn.py broker Gateway，也没有宣称任何 Gateway 的账户或实盘成熟度；
- paper 测试只使用 fake MainEngine/Gateway 和真实 vn.py DTO，不连接券商；
- vn.py OMS 是进程内 callback cache，不作为可靠 broker query/reconciliation 来源；
- 详细模式、live gate 和映射限制见 `vnpy-transport.md`。

执行恢复矩阵当前提供 additive、完全离线的自动化证据：

- `qexec recovery-matrix` 覆盖 timeout、重复/乱序 callback、重启、撤单成交竞态、重连和持仓漂移；
- 输出严格、byte-stable 的 `execution_recovery_matrix.v1`，明确声明
  `deterministic=true` 和 `live_broker_access=false`；
- shadow/paper 两种标签都只使用本地 fake transport 和 SQLite journal，不证明任何真实 Gateway
  或券商恢复能力；
- 真实 accepted-but-timeout 和 position drift 仍必须按操作员 runbook 查询券商权威事实并人工复核。

- 带有 `--execute` 参数的调仓命令已为长桥实盘、长桥模拟盘、Alpaca 模拟盘和盈透模拟盘打通了真实的券商底层代码链路，但各后端的成熟度存在差异（如上表所述）。
- 目前 `--account` 参数仅用于账户或配置标签的解析与快速失败校验，暂不具备真实的多账户路由能力。
- 长桥实盘、长桥模拟盘、Alpaca 模拟盘和盈透模拟盘的适配器目前均按单账户语义运行。传入不支持的账户标签会直接报错拦截。
- `orders`、`exceptions` 以及 `order` 命令展示的是本地追踪状态视图。
- 券商订单与成交记录查询是单独的只读查询命令；它们只在支持该能力的后端上可用，目前主要用于补充排障与审计视角，而不改变本地追踪状态的权威语义。
- 订单追踪命令会把本地追踪状态的母订单、子订单与成交记录，与支持后端上的券商历史做联合展示；当后端不支持历史时，该命令仍可返回本地追踪记录，并附带只读历史不可用的提示。
- 订单重试指令（`retry`）仅支持零成交且已处于终态的追踪订单。对于部分成交的订单，必须使用撤销剩余（`cancel-rest`）、继续执行剩余（`resume-remaining`）或接受部分成交（`accept-partial`）指令来处理。
- 调仓的输入必须是规范的 `targets.json` 文件。旧版的纯代码列表、仅包含权重的文档或表格文件格式已不再作为对外支持的执行输入。
- 上游研究证据、lineage sidecar 和执行层 paper/live 分层的边界见 `research-handoff-governance.md`。

## 凭证加载规则

- 长桥模拟盘允许从项目本地的 `.env` 或 `.env.local` 文件中读取模拟盘令牌。
- 长桥实盘默认优先读取 `~/.config/qexec/longport-live.env` 文件，其次读取当前进程的环境变量。项目本地的配置文件中绝对不能包含长桥的实盘凭证。
- 系统会首先检查当前进程环境变量中的实盘开关，若未设置，则回退读取私有配置文件。
- 使用 `qexec config --broker longport` 和 `qexec config --broker longport-paper` 命令可以清晰查看长桥各项核心参数的最终命中来源，便于操作员确认当前使用的是本地测试配置还是私有实盘配置。
- 以 `LONGBRIDGE_` 开头的环境变量名已被弃用，仅作向下兼容保留。新配置与操作文档均应统一使用 `LONGPORT_` 前缀。

## 测试运行入口

- 快速默认测试：`uv run pytest`
- 端到端测试：`uv run pytest -m e2e`
- 集成测试：`uv run pytest -m integration`
- 按需生成测试覆盖率报告，例如：

```bash
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

涉及真实券商后端的冒烟测试证据，均依赖操作员的人工监督，且与底层运行环境强相关。各后端的冒烟测试操作手册中已详细说明了所需的凭证与本地运行环境的前置条件。

## 输出目录说明

- 调仓审计日志：`outputs/orders/*.jsonl`
- 本地执行状态：`outputs/state/*.json`
- 冒烟测试证据：`outputs/evidence/*.json`
- 证据打包归档：`outputs/evidence-bundles/*`

注意：输出目录已被代码版本控制忽略。所有证据文件仅作为本地复查档案留存，不应作为测试用例夹具随代码提交。

## 项目工具

面向量化操作员的冒烟测试工装：

- `project_tools/smoke_signal_harness.py`
- `project_tools/smoke_target_harness.py`
- `project_tools/smoke_operator_harness.py`

仅供核心维护者使用的工具：

- `project_tools/export_repo_source.py`
- `project_tools/package.sh`

这些维护者工具不属于产品业务流程，仅用于源码导出与归档打包等任务。
