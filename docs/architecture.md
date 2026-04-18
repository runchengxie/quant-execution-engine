# 项目架构

## 项目定位

`quant_execution_engine` 定位为一个纯粹的量化执行引擎。

当前支持矩阵、证据成熟度和 shared caveats 以
[current-capabilities.md](current-capabilities.md) 为准。

它负责：

*   提供券商底层的适配、接口能力矩阵以及凭证封装。
*   获取账户资金持仓快照与拉取实时行情。
*   基于目标持仓生成调仓计划，并提供调仓前后的差异预览。
*   支持预演（Dry-run）、实盘和模拟盘的完整调仓落地流程。
*   维护从订单意图、母子订单流转、成交回报到状态对账的完整生命周期。
*   落实执行层的风控拦截与紧急停单机制。
*   提供执行前的就绪性检查（Preflight）、本地状态维护工具以及面向操作员的终端命令行交互。
*   负责生成审计日志、持久化本地执行状态，并提供用于验证的冒烟测试工装。

它不负责：

*   策略研究、历史回测或 Alpha 挖掘。
*   基础行情数据的清洗导入与因子计算。
*   跨券商的多账户统一路由与资金调拨中台。
*   提供 TWAP、POV 等复杂的算法交易执行调度框架（当前侧重于基础执行闭环）。

## 包结构

```text
src/quant_execution_engine/
  __init__.py
  __main__.py
  cli.py
  cli_parser.py
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
  execution_service.py
  execution_service_recovery.py
  execution_service_recovery_actions.py
  execution_service_state_reconcile_ops.py
  evidence_maturity.py
  evidence_bundle.py
  execution_state.py
  diagnostics.py
  guards.py
  preflight.py
  risk.py
  state_tools.py
  broker/
    __init__.py
    base.py
    factory.py
    alpaca.py
    ibkr.py
    ibkr_runtime.py
    _stubs.py
    longport_adapter.py
    longport_credentials.py
    longport_support.py
    longport.py
  renderers/
    __init__.py
    diff.py
    jsonout.py
    table.py
project_tools/
  export_repo_source.py
  smoke_signal_harness.py
  smoke_target_harness.py
  smoke_operator_harness.py
```

## 分层说明

*   `cli.py`
    作为命令行主入口，负责券商后端路由、命令分发与统一的错误处理。包含就绪性检查、人工干预恢复以及本地状态维护等命令。
*   `cli_parser.py`
    负责构建命令行的参数树与参数声明，是将命令行定义逻辑剥离出的独立模块。
*   `broker/base.py` 与 `broker/factory.py`
    定义券商接口的标准化生命周期、能力支持矩阵，以及多后端的工厂选择逻辑。
*   `broker/` 目录下的具体实现
    分别负责长桥（LongPort）SDK 的底层封装及其对应的实盘/模拟盘适配、Alpaca 模拟盘适配，以及盈透（IBKR）本地网关的运行环境与模拟盘适配。
*   `broker/longport_credentials.py`
    处理长桥实盘与模拟盘的鉴权凭证解析，确保不同配置环境相互隔离，并规避占位符配置导致的异常。
*   `broker/longport_support.py`
    提供长桥运行期的通用支持函数，避免 SDK 的底层细节泄漏到命令行顶层。
*   `account.py`
    通过底层券商适配器，统一处理账户资产快照与行情查询业务。
*   `rebalance.py`
    核心调仓模块，负责解析目标仓位、生成订单执行计划、调用执行入口，并记录完整的审计日志。
*   `execution.py`
    包导出文件，对外提供统一的执行生命周期相关类型和服务的引入路径。
*   `execution_service.py`
    执行服务的主流程编排，涵盖订单提交、状态对账、撤单操作以及异常状态的视图聚合。
*   `execution_service_recovery.py`
    提供异常恢复模块的向下兼容引入路径。
*   `execution_service_recovery_actions.py`
    实现各项人工干预与恢复动作，包括重试订单、重新定价、撤销未成交部分、继续执行剩余订单、接受部分成交结果，以及清理过期订单等。
*   `execution_service_state_reconcile_ops.py`
    处理底层的状态同步细节，包括执行状态的持久化、对账数据的合并、本地已跟踪订单的同步与状态标记。
*   `evidence_maturity.py`
    梳理并汇总各券商后端的代码支持度及测试留存情况，并给出下一步冒烟测试建议，供系统生成成熟度报告使用。
*   `evidence_bundle.py`
    根据运行编号（Run ID）打包收集单次执行的完整复查材料，包含审计日志、目标清单、本地状态、测试证据以及操作员备注。
*   `execution_state.py`
    定义执行生命周期的数据结构、状态枚举，并实现基于本地文件的状态持久化存储。
*   `diagnostics.py`
    诊断模块，负责将券商接口返回的原始错误码与本地异常状态，转化为操作员易于理解的归一化诊断信息与排查建议。
*   `guards.py`
    安全拦截模块，负责实盘执行前的强制确认，并扫描排查，防止实盘密钥遗留在本地代码仓库中。
*   `preflight.py`
    执行前置检查模块，在不改变券商实际状态的前提下，验证账户、网络与数据的就绪情况。
*   `state_tools.py`
    本地状态维护工具，提供状态文件的一致性体检、旧数据清理和异常修复功能。
*   `risk.py`
    风控模块，负责订单维度的执行风控拦截与由环境变量触发的紧急停单逻辑。
*   `targets.py`
    规范定义持仓目标数据结构（即 `targets.json` 的 Schema），并提供对应的解析与校验功能。
*   `renderers/` 目录
    视图渲染层，负责将核心数据格式化为表格、JSON、调仓差异对比图及终端摘要信息。
*   `project_tools/` 目录
    项目独立工具箱，包含生成测试信号、模拟持仓目标、操作员流程跑通测试（冒烟测试）等脚本。这些工装主要用于系统行为验证，与核心业务代码保持物理隔离。

## 设计取向

*   职责直白：模块命名直接体现业务职能，避免过度抽象或过早引入平台化的宏大命名。
*   收敛输入边界：实盘下单的唯一指令输入，严格限定为标准化的 `targets.json` 目标持仓文件。
*   本地状态优先：以本地持久化的订单状态，作为系统防重报（幂等性）、异常恢复以及人工接管的核心底层依据。
*   视图职责清晰：系统的订单查询命令（如 `orders` 和 `exceptions`）仅展示本引擎已记录且正在跟踪的订单状态，绝不将其伪装或等同于券商后端的全量订单簿。
*   网关依赖模式：针对盈透证券（IBKR），将其定位为依赖本地运行环境的后端，目前严格通过本地部署的 IB Gateway 配合 TWS API 进行接入，而非视作纯云端接口。

## 当前限制

*   单账户模式：虽然命令行已支持传递账户参数并进行显式校验，但目前所有接入的券商（长桥实盘及模拟盘、Alpaca 模拟盘、盈透模拟盘）在底层均按单账户逻辑运行，暂不具备真实的多账户路由与切换能力。
*   部分成交恢复的限制：对于发生部分成交后的“继续执行剩余订单”操作，当前仅支持整数股的继续申报；更复杂的碎股处理或算法拆单调度暂不在支持范围内。
*   风控依赖市场数据：买卖价差、参与率以及市场冲击等风控指标均强依赖券商下发的实时行情。若无法获取有效行情，系统会如实记录为跳过校验（Bypass），而不会强行捏造伪指标来阻断交易。
*   实盘验证成熟度：长桥实盘的代码执行链路虽已打通，但出于资金安全考虑，其全自动的端到端测试证据目前仍弱于 Alpaca 模拟盘，实盘的验证仍须依赖人工监督按步骤推进。
*   配置读取策略分化：长桥模拟盘优先读取项目本地的测试配置文件，而实盘则强制优先从用户级的私有目录（`~/.config/...`）读取。此举旨在确保模拟盘测试可随时被重复执行，同时彻底隔绝实盘密钥遗留在代码库的风险。
*   盈透模拟盘处于早期支持：目前盈透仅支持美股正股的最基础交易切片，且强依赖本地已登录的客户端。虽然现有的测试记录已证明代码能够成功连接网关并完成账户对账，但在实际市场行情下的完整订单流转（报单、成交、撤单）测试证据仍需在后续的冒烟测试中进一步补齐。
