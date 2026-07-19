# 架构

`quant_execution_engine` 负责把标准目标持仓转换为可审计的执行计划和订单生命周期。券商支持程度见 [current-capabilities.md](current-capabilities.md)，生命周期细节见 [execution-foundation.md](execution-foundation.md)。

## 数据流

```text
targets.json
  → 解析与交接审计
  → 账户和行情快照
  → 调仓计划与执行风控
  → 券商适配器
  → 本地订单状态与对账
  → 审计日志和证据包
```

执行层的输入边界止于目标持仓。因子研究、历史回测、行情清洗和候选晋升由上游仓库完成。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `cli.py`、`cli_parser.py` | 命令分发、参数声明、操作员输出和统一错误处理 |
| `targets.py` | `targets.json` 解析、市场归一和写入工具 |
| `handoff_audit.py` | 校验目标与 lineage 文件的存在性和哈希，不改变订单参数 |
| `account.py`、`rebalance.py` | 读取账户与行情，统一币种估值，生成调仓计划 |
| `fees.py`、`fx.py` | 手续费估算和汇率读取 |
| `risk.py`、`guards.py` | 订单风控、紧急停单和实盘凭证保护 |
| `preflight.py`、`health.py` | 执行前就绪检查和本地状态体检汇总 |
| `broker/base.py`、`broker/factory.py` | 券商协议、能力声明、后端选择和账户标签解析 |
| `broker/local_dry_run.py` | 无网络的文件契约预演 |
| `broker/alpaca.py` | Alpaca 模拟盘适配 |
| `broker/ibkr.py`、`broker/ibkr_runtime.py` | 盈透模拟盘适配和本地网关运行时 |
| `broker/longport*.py` | 长桥 SDK、凭证、代码转换及模拟盘与实盘适配 |
| `execution_service*.py` | 提交、状态合并、对账和人工恢复动作 |
| `execution_state.py`、`state_tools.py` | 本地生命周期模型、持久化、诊断和修复 |
| `diagnostics.py` | 把后端错误归一为操作员可用的排查信息 |
| `evidence_bundle.py`、`evidence_maturity.py`、`report.py` | 证据打包、成熟度汇总和运行报告 |
| `domain.py`、`serialization.py`、`_serialization_*.py` | 不可变领域对象、v1 迁移读取和严格 v2 wire codec |
| `execution_policy.py`、`execution_helpers.py` | 已批准目标的执行策略计算和共享辅助函数 |
| `facade.py` | 为外部 Python 调用方提供简化执行接口 |
| `renderers/` | 表格、JSON 和调仓差异视图 |
| `project_tools/` | 操作员演练、测试信号和目标生成工装 |

`models.py` 仍承载 CLI 和文件状态链路使用的可变 DTO。新领域边界及迁移规则见 [typed-execution-domain.md](typed-execution-domain.md)。

## 分层原则

### 目标与计划

`targets.py` 只解释目标文件。`rebalance.py` 结合账户、行情、汇率、费用和手数规则生成计划。默认预演不会提交订单。

### 风控与执行

`risk.py` 为每项检查产出结构化结果。`execution_service.py` 在本地登记意图后调用券商适配器，并把后端结果写回生命周期状态。

### 后端隔离

业务编排依赖 `BrokerAdapter`，各券商的 SDK 和连接细节留在 `broker/`。能力矩阵用于快速拒绝后端不支持的操作。

当前框架层只维护通用 `BrokerAdapter` 和类型化领域边界。具体实现包括 Alpaca 模拟盘、IBKR 模拟盘、LongPort 模拟盘与实盘，以及本地预演后端。

当前 `main` 没有 vn.py 适配器、依赖或已注册后端。Qlib、LEAN、Backtrader 及其他研究或回测框架不在本仓库范围内。外部 Gateway 或框架的接入需要独立定义事件归一、幂等、重启恢复、对账和回滚证据。

### 状态与证据

本地状态用于防重报、恢复和操作员查询。对账把券商事实合并到已追踪订单。审计日志和证据包为复查提供独立材料。

## 当前约束

- 各后端按单账户语义运行。
- `orders` 等命令展示引擎已追踪的订单范围，不代表券商完整订单簿。
- 部分成交后的继续执行当前限整数数量。
- 点差、参与率和冲击检查依赖有效市场数据。缺少数据时会记录降级结果。
- 盈透当前限美股正股，并依赖已登录的本地网关。
- 复杂拆单、算法调度和跨券商资金路由不在当前范围内。
- 通用事件引擎和第三方交易框架适配不在当前范围内。

历史完成清单保存在 [archive/](archive/)。
