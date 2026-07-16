# 当前能力

本页记录已注册的券商后端、可验证的执行范围和证据成熟度。命令细节见 [cli.md](cli.md)，凭证和保护开关见 [configuration.md](configuration.md)。

## 后端矩阵

| 后端 | 用途 | 前置条件 | 当前证据和限制 |
| --- | --- | --- | --- |
| `local-dry-run` | 无网络的目标文件解析、合成行情和调仓预演 | 安装 `cli` 额外依赖 | 适合文件契约和手数规则回归，不提供提交、撤单、订单查询或对账 |
| `alpaca-paper` | Alpaca 模拟盘提交、查询、撤单和对账 | 安装 `alpaca` 额外依赖并配置模拟盘凭证 | 是低成本模拟盘回归基线，当前没有 Alpaca 实盘后端 |
| `alpaca` | `alpaca-paper` 的兼容别名 | 与 `alpaca-paper` 相同 | 仍按模拟盘语义运行 |
| `longport-paper` | 长桥模拟盘的账户、行情、提交、查询、撤单和对账 | 安装 `longport` 额外依赖并配置模拟盘令牌 | 已有人工监督下的基础链路证据，失败场景仍需持续补充 |
| `longport` | 长桥实盘读取和执行 | 安装 `longport` 额外依赖，使用仓库外实盘凭证，执行时设置 `QEXEC_ENABLE_LIVE=1` | 只读检查和保护机制已有证据，完整实盘订单证据仍有限 |
| `ibkr-paper` | 依赖本地 IB Gateway 的盈透模拟盘最小链路 | 安装 `ibkr` 额外依赖，启动并登录网关，配置连接参数 | 当前限美股正股。连接、账户、行情和无报单流程已有证据，仍缺有效行情下的完整报单与成交证据 |

## A 股文件契约

`targets.json` 支持 `market: CN`，`local-dry-run` 可验证解析、合成估值和 100 股手数规则。`.SH`、`.SZ`、`.BJ` 应保留，`.XSHG` 和 `.XSHE` 会归一为对应交易所后缀。

当前已注册后端没有提供经过验证的中国大陆市场真实报单能力。账户权限、券商接口和交易通道需要独立验收。

## 共享执行语义

- 当前没有默认券商，每次运行需通过配置或 `--broker` 选择后端。
- `--account` 用于账户标签解析和快速失败校验。各后端当前按单账户语义运行。
- `qexec rebalance` 默认只生成计划。`--execute` 才会进入后端提交链路，后端能力和保护开关仍会继续校验。
- `orders`、`exceptions` 和 `order` 展示本地追踪状态。
- 券商历史查询提供只读补充视图，不改变本地追踪状态。
- `retry` 只适用于零成交且已进入终态的追踪订单。部分成交使用 `cancel-rest`、`resume-remaining` 或 `accept-partial`。
- 调仓指令只接受标准 `targets.json`。目标字段和市场推断见 [targets.md](targets.md)。
- 研究证据和 lineage sidecar 的边界见 [research-handoff-governance.md](research-handoff-governance.md)。

## 凭证边界

- 长桥模拟盘可以读取项目本地 `.env` 或 `.env.local`。
- 长桥实盘优先读取 `~/.config/qexec/longport-live.env`，也可读取当前进程环境变量。
- 项目本地 `.env*` 和 `.envrc*` 不得包含长桥实盘凭证。
- `LONGBRIDGE_` 前缀仅保留兼容读取，新配置统一使用 `LONGPORT_`。

详细字段和来源优先级见 [configuration.md](configuration.md)。

## 本地产物

| 路径 | 内容 |
| --- | --- |
| `outputs/orders/*.jsonl` | 调仓审计日志 |
| `outputs/state/*.json` | 本地执行状态 |
| `outputs/evidence/*.json` | 演练证据 |
| `outputs/evidence-bundles/*` | 单次运行复查包 |

这些路径默认被 Git 忽略。证据成熟度需要结合受监督演练和产物复查，不能只依据代码路径判断。

## 操作员工装

- `project_tools/smoke_signal_harness.py`
- `project_tools/smoke_target_harness.py`
- `project_tools/smoke_operator_harness.py`

`project_tools/export_repo_source.py` 和 `project_tools/package.sh` 用于源码导出与归档，不属于交易流程。
