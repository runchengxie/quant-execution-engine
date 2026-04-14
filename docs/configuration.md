# 变量设置

## 环境变量

### LongPort 模拟盘/实盘

必需：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

提交保护：

- `qexec rebalance --execute` 在 real broker 路径下要求 `QEXEC_ENABLE_LIVE=1`
- repo 根目录下的 `.env*` / `.envrc*` 如果包含 LongPort live 凭证，CLI 会拒绝执行
- 这条保护的目的是防止把 real secret 留在仓库本地文件里；paper 凭证不受这个限制

可选：

- `LONGPORT_REGION`
- `LONGPORT_ENABLE_OVERNIGHT`
- `LONGPORT_MAX_NOTIONAL_PER_ORDER`
- `LONGPORT_MAX_QTY_PER_ORDER`
- `LONGPORT_TRADING_WINDOW_START`
- `LONGPORT_TRADING_WINDOW_END`
- `FX_<CCY>_USD`，例如 `FX_HKD_USD=0.128`
- `LONGPORT_FX_<CCY>_USD`，例如 `LONGPORT_FX_HKD_USD=0.128`

兼容读取：

- 旧的 `LONGBRIDGE_*` 前缀仍会被兼容读取
- `LONGPORT_ACCESS_TOKEN_REAL` 仍会作为 `LONGPORT_ACCESS_TOKEN` 的兼容兜底
- `LONGPORT_FX_<CCY>_USD` 会作为 `FX_<CCY>_USD` 的兼容兜底

### Alpaca 模拟盘/实盘

必需：

- `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

说明：

- Alpaca 支持来自可选依赖 `alpaca-py`，安装方式：`uv sync --extra alpaca`
- 如果你使用仓库自带的 `.envrc` / `.envrc.example`，并且 `.env` 或 `.env.local` 里已经有 `ALPACA_*` / `APCA_*` 凭证，direnv 载入目录时会自动把 `--extra alpaca` 加进 `uv sync`
- 当前 adapter 以 paper 为默认模式，不提供多账户切换

## 本地 YAML

复制模板：

```bash
cp config/template.yaml config/config.yaml
```

当前 execution-engine 主要读取这些字段：

- `broker`
- `execution`
- `fees`
- `fractional_preview`
- `fx`

示例：

```yaml
broker:
  backend: longport
  default_account: main
  accounts:
    main: {}

execution:
  state_dir: outputs/state
  risk:
    max_qty_per_order: 0
    max_notional_per_order: 0
    max_spread_bps: 0
    max_participation_rate: 0
    max_market_impact_bps: 0
  kill_switch:
    env_var: QEXEC_KILL_SWITCH
    failure_threshold: 3

fees:
  domicile: HK
  commission: 0.0
  platform_per_share: 0.005
  fractional_pct_lt1: 0.012
  fractional_cap_lt1: 0.99
  sell_reg_fees_bps: 0.0

fractional_preview:
  enable: true
  default_step: 0.001

fx:
  to_usd:
    HKD: 0.128
```

也兼容这个 FX 结构：

```yaml
fx:
  rates:
    HKDUSD: 0.128
```

## 加载顺序

配置文件按这个顺序查找：

1. `config/config.yaml`
2. `config.yaml`

都不存在时，运行时使用空配置。

## 行为说明

- `LONGPORT_TRADING_WINDOW_START/END` 只是 session API 不可用时的本地降级判断。
- `LONGPORT_MAX_QTY_PER_ORDER` 只在非 dry-run 路径强制拦截。
- `LONGPORT_MAX_NOTIONAL_PER_ORDER` 当前只做告警提示，不会在本地直接拦截；最终仍以 broker 风控为准。
- LongPort real `--execute` 需要显式设置 `QEXEC_ENABLE_LIVE=1` 作为二次确认。
- LongPort real `--execute` 会拒绝使用 repo 根目录 `.env*` / `.envrc*` 中的 live 凭证，避免本地 secret 文件随仓库传播。
- execution risk gate 的主要本地阈值改为读 `execution.risk.*`。
- `execution.kill_switch.env_var` 和可选 `execution.kill_switch.path` 可以手动停掉新的 broker submit。
- `broker.default_account` 是 CLI 没显式传 `--account` 时的默认 label；如果 adapter 不支持该 label，会直接报错。
- `execution.state_dir` 控制幂等/恢复状态文件目录，默认是 `outputs/state`。
