# 项目架构

## 项目定位

`quant_execution_engine` 是一个纯执行引擎。

它负责：

- 券商适配层、能力矩阵与凭证封装
- 账户快照与行情抓取
- 调仓计划生成与差异预览
- 预演 / 实盘 / 模拟盘调仓流程
- order intent / parent-child order / fill / reconcile 生命周期
- 执行风控门禁与紧急停单
- `preflight`、状态维护和操作员终端输出
- 审计输出、状态持久化与冒烟测试工装

它不负责：

- 研究 / 回测 / alpha
- 数据导入或因子计算
- 多账户统一路由中台
- 完整的 TWAP / POV / 算法执行框架

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

- `cli.py`
  负责券商后端选择、命令分发和错误码收口，包括 `preflight`、操作员恢复命令和本地状态维护命令。
- `cli_parser.py`
  负责 `qexec` 参数树构建与命令参数声明，作为 CLI 机械性定义的独立模块。
- `broker/base.py` / `broker/factory.py`
  定义券商生命周期契约、能力矩阵和后端选择逻辑。
- `broker/longport.py` / `broker/longport_adapter.py` / `broker/alpaca.py` / `broker/ibkr.py` / `broker/ibkr_runtime.py`
  分别负责 LongPort SDK 封装、LongPort 实盘/模拟盘适配器、Alpaca 模拟盘适配器，以及 IBKR paper runtime 和适配器实现。
- `broker/longport_credentials.py`
  负责 LongPort 实盘/模拟盘的凭证解析、配置隔离和占位值规避。
- `broker/longport_support.py`
  放置 LongPort 运行期支持函数，避免把 SDK 适配细节继续塞进 CLI。
- `account.py`
  负责通过适配器获取账户快照与行情查询。
- `rebalance.py`
  负责目标仓位计算、订单规划、执行入口和审计日志。
- `execution.py`
  作为兼容出口，保留执行生命周期相关类型和服务的导出。
- `execution_service.py`
  负责订单提交流程、对账入口、取消入口和异常视图聚合等主流程编排。
- `execution_service_recovery.py`
  作为兼容出口，保留 recovery mixin 的稳定导入路径。
- `execution_service_recovery_actions.py`
  负责 retry / reprice / cancel-rest / resume-remaining / accept-partial / stale-retry 等操作员恢复动作。
- `execution_service_state_reconcile_ops.py`
  负责 execution state 写入、reconcile 合并、tracked order 同步和本地状态标记等底层细节。
- `evidence_maturity.py`
  负责汇总各 broker 的代码路径状态、已有证据和下一步 smoke 建议，供 `qexec evidence-maturity` 使用。
- `evidence_bundle.py`
  负责按审计 `run_id` 收拢 audit / targets / state / smoke evidence / operator note，供 `qexec evidence-pack` 使用。
- `execution_state.py`
  负责执行生命周期数据类、状态常量和基于文件的状态存储。
- `diagnostics.py`
  负责把券商侧与本地订单的异常状态、告警统一成更适合操作员理解的诊断信息。
- `guards.py`
  负责实盘执行二次确认和仓库本地密钥扫描。
- `preflight.py`
  负责不修改券商状态的就绪性检查。
- `state_tools.py`
  负责本地状态的 doctor / prune / repair。
- `risk.py`
  负责执行风控门禁和紧急停单逻辑。
- `targets.py`
  负责标准 `targets.json` 的 schema 与读写。
- `renderers/`
  负责表格、JSON、差异视图和操作员摘要输出。
- `project_tools/`
  放置信号驱动、目标持仓驱动、操作员冒烟工装和仓库导出辅助脚本，作为验证 / 辅助工装，与策略层保持分离。

## 设计取向

- 让模块名直接表达职责，避免平台化命名先行。
- 实盘执行输入边界严格收敛到统一的 `targets.json`。
- 本地状态是幂等、恢复和操作员处置的基础面。
- `orders` / `exceptions` / `order` 明确是已跟踪状态视图，不伪装成券商全量订单簿。
- IBKR 属于本地 broker runtime 依赖型 backend；当前通过本地 IB Gateway over TWS API 接入。

## 当前限制

- `--account` 已支持显式校验参数，但当前 LongPort 实盘、`longport-paper`、Alpaca 模拟盘和 `ibkr-paper` 都按单账户模式运行，不支持真实多账户切换。
- `resume-remaining` 当前只支持整数股剩余量；更复杂的碎股或算法单调度仍不在范围内。
- 风控门禁里的 spread / participation / impact 依赖券商提供的市场数据；拿不到时会记录 `BYPASS`，不生成伪指标。
- LongPort 实盘路径已经存在，但自动化端到端证据仍弱于 Alpaca 模拟盘冒烟。
- `longport-paper` 默认优先读取仓库本地 `.env` / `.env.local`，LongPort 实盘默认优先读取 `~/.config/qexec/longport-live.env`；这是为了同时保住模拟盘冒烟的可重复性和实盘凭证隔离。
- `ibkr-paper` 当前只覆盖 US equities 最小切片，并依赖本地已登录的 IB Gateway；仓库内已有一次 operator-supervised no-order evidence 样例，证明 WSL -> Windows Gateway/account/reconcile 路径可达，但 broker order 提交、成交、撤单证据仍需有效行情下的下一次 paper smoke 补齐。
