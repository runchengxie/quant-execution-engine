# 变量设置

## 环境变量

### LongPort live

必需：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

提交保护：

- `qexec rebalance --execute` 在 real broker 路径下要求 `QEXEC_ENABLE_LIVE=1`
- repo 根目录下的 `.env*` / `.envrc*` 如果包含 LongPort live 凭证，CLI 会拒绝执行
- 这条保护的目的是防止把 real secret 留在仓库本地文件里；paper 路径不受这个限制

可选：

- `LONGPORT_REGION`
- `LONGPORT_ENABLE_OVERNIGHT`
- `LONGPORT_TRADING_WINDOW_START`
- `LONGPORT_TRADING_WINDOW_END`
- `FX_<CCY>_USD`，例如 `FX_HKD_USD=0.128`
- `LONGPORT_FX_<CCY>_USD`，例如 `LONGPORT_FX_HKD_USD=0.128`

### LongPort paper

必需：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN_TEST`

说明：

- LongPort real 和 paper 共用 App Key / Secret，但使用不同 Access Token。
- 当前 `longport-paper` backend 会优先读取 `LONGPORT_ACCESS_TOKEN_TEST`。

兼容读取：

- 旧的 `LONGBRIDGE_*` 前缀仍会被兼容读取
- `LONGPORT_ACCESS_TOKEN_REAL` 仍会作为 `LONGPORT_ACCESS_TOKEN` 的兼容兜底
- `LONGPORT_FX_<CCY>_USD` 会作为 `FX_<CCY>_USD` 的兼容兜底

兼容限额变量：

- `LONGPORT_MAX_NOTIONAL_PER_ORDER`
- `LONGPORT_MAX_QTY_PER_ORDER`

这两个变量仍会被兼容读取，但当前 CLI 主执行路径更推荐通过 `execution.risk.*` 配置本地风控阈值。

### LongPort 读取优先级

当前项目把 LongPort 的 paper 和 real 路径故意分开处理：

- `longport-paper`：优先读取 repo 根目录 `.env` / `.env.local`，其次读取当前进程环境变量，最后才回退到 `~/.config/qexec/longport-live.env`
- `longport` real：优先读取 `~/.config/qexec/longport-live.env`，其次读取当前进程环境变量

这样做的目的很直接：

- paper / smoke 保持以项目内测试配置为主，不容易被外部残留环境变量串偏
- real 路径默认走用户私有配置，不把 live token 放进 repo 本地文件

另外：

- `QEXEC_ENABLE_LIVE` 会先读当前进程环境变量；如果没设置，再回退到 `~/.config/qexec/longport-live.env`
- `qexec config --broker longport` 和 `qexec config --broker longport-paper` 现在会显示 App Key / Secret / Token / Region / Overnight 的命中来源，便于排查到底读到了哪一层配置

### Alpaca paper

必需：

- `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

说明：

- Alpaca 支持来自可选依赖 `alpaca-py`，安装方式：`uv sync --extra alpaca`
- 当前 adapter 是 paper-only 验证路径，不提供实盘切换
- 当前也不提供真实多账户切换

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

也兼容这个汇率结构：

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

- `execution.risk.*` 是当前 CLI 主执行路径的主要本地风控来源。
- `LONGPORT_TRADING_WINDOW_START/END` 只是 session API 不可用时的本地降级判断。
- `LONGPORT_MAX_QTY_PER_ORDER` 和 `LONGPORT_MAX_NOTIONAL_PER_ORDER` 更偏兼容层 / legacy client 语义，不应该替代 `execution.risk.*`。
- `execution.kill_switch.env_var` 和可选 `execution.kill_switch.path` 可以手动停掉新的 broker submit。
- `broker.default_account` 是 CLI 没显式传 `--account` 时的默认 label；如果 adapter 不支持该 label，会直接报错。
- `execution.state_dir` 控制幂等 / 恢复状态文件目录，默认是 `outputs/state`。
