# 配置说明

当前 broker 支持范围、凭证来源规则和证据成熟度以
[current-capabilities.md](current-capabilities.md) 为准。本文聚焦配置入口。

## 环境变量

### LongPort 实盘

必需：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

提交保护：

- `qexec rebalance --execute` 在实盘路径下要求 `QEXEC_ENABLE_LIVE=1`
- 仓库根目录下的 `.env*` / `.envrc*` 如果包含 LongPort 实盘凭证，CLI 会拒绝执行
- 这条保护的目的是防止把实盘密钥留在仓库本地文件里；模拟盘路径不受这个限制
- `.env.example` 只示范本地 paper/smoke 配置，不包含 `LONGPORT_ACCESS_TOKEN` 实盘占位符

可选：

- `LONGPORT_REGION`
- `LONGPORT_ENABLE_OVERNIGHT`
- `LONGPORT_TRADING_WINDOW_START`
- `LONGPORT_TRADING_WINDOW_END`
- `FX_<CCY>_USD`，例如 `FX_HKD_USD=0.128`
- `LONGPORT_FX_<CCY>_USD`，例如 `LONGPORT_FX_HKD_USD=0.128`

### LongPort 模拟盘

必需：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN_TEST`

说明：

- 长桥实盘和模拟盘共用 App Key / Secret，但使用不同的 Access Token。
- 当前长桥模拟盘后端会优先读取 `LONGPORT_ACCESS_TOKEN_TEST`。

弃用兼容读取：

- 旧的 `LONGBRIDGE_*` 前缀仍会兼容读取，但新配置和文档应使用 `LONGPORT_*`
- `LONGPORT_ACCESS_TOKEN_REAL` 仍会作为 `LONGPORT_ACCESS_TOKEN` 的兼容兜底
- `LONGPORT_FX_<CCY>_USD` 会作为 `FX_<CCY>_USD` 的兼容兜底

兼容限额变量：

- `LONGPORT_MAX_NOTIONAL_PER_ORDER`
- `LONGPORT_MAX_QTY_PER_ORDER`

这两个变量仍会被兼容读取，但当前 CLI 主执行路径更推荐通过 `execution.risk.*` 配置本地风控阈值。

### 长桥证券读取优先级

当前项目刻意把长桥的模拟盘和实盘路径分开处理：

- `longport-paper`：优先读取仓库根目录 `.env` / `.env.local`，其次读取当前进程环境变量，最后才回退到 `~/.config/qexec/longport-live.env`
- `longport` 实盘：优先读取 `~/.config/qexec/longport-live.env`，其次读取当前进程环境变量

这样做的目的很直接：

- 模拟盘和冒烟测试以项目内测试配置为主，不容易被外部残留环境变量带偏
- 实盘路径默认走用户私有配置，不把实盘 token 放进仓库本地文件

另外：

- `QEXEC_ENABLE_LIVE` 会先读当前进程环境变量；如果没设置，再回退到 `~/.config/qexec/longport-live.env`
- `qexec config --broker longport` 和 `qexec config --broker longport-paper` 会显示 App Key / Secret / Token / Region / Overnight 的命中来源，便于排查到底读到了哪一层配置

### Alpaca 模拟盘

必需：

- `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

说明：

- Alpaca 支持来自可选依赖 `alpaca-py`，安装方式：`uv sync --extra alpaca`
- 当前适配器是纯模拟盘验证路径，不提供实盘切换
- 当前也不提供真实多账户切换

### 盈透证券模拟盘

必需：

- 本地已启动并登录的 IB Gateway
- `IBKR_HOST`，默认 `127.0.0.1`
- `IBKR_PORT` 或 `IBKR_PORT_PAPER`，默认 `4002`
- `IBKR_CLIENT_ID`，默认 `1`

可选：

- `IBKR_ACCOUNT_ID`
- `IBKR_CONNECT_TIMEOUT_SECONDS`，默认 `5`

说明：

- 当前盈透证券模拟盘后端按本地 `IB Gateway + TWS API` 路线运行。
- 当前只支持 US equities 最小切片；非 `.US` symbol 会在适配器层快速失败。
- `qexec config --broker ibkr-paper` 会显示 host / paper port / client ID / account ID / timeout 的有效值和来源。
- 真实多账户路由不在当前范围内；`--account` 仍只接受 `main`。

### 安装模型

- 核心安装：`uv sync --group dev --extra cli`
- LongPort：`uv sync --group dev --extra cli --extra longport`
- Alpaca：`uv sync --group dev --extra cli --extra alpaca`
- IBKR：`uv sync --group dev --extra cli --extra ibkr`
- 全量 broker 依赖：`uv sync --group dev --extra cli --extra full`
- 当前 CLI 不再假设默认 broker；请在本地 YAML 里显式设置 `broker.backend`，或每次传 `--broker`

### `.envrc.example`

仓库里的 `.envrc.example` 和 tracked `.envrc` 使用同一套模型，默认使用：

```bash
uv sync --group dev --extra cli
```

如果 `.env` / `.env.local` 或当前 shell 里已经有对应 broker 的环境变量，它会自动追加相关可选依赖：

- Alpaca 变量命中时追加 `--extra alpaca`
- LongPort / deprecated LongBridge 兼容变量命中时追加 `--extra longport`
- IBKR 变量命中时追加 `--extra ibkr`

`.envrc` 仍然是 repo-local 文件，不应写入 LongPort 实盘 token。实盘推荐：

```bash
export LONGPORT_APP_KEY=...
export LONGPORT_APP_SECRET=...
export LONGPORT_ACCESS_TOKEN=...
export QEXEC_ENABLE_LIVE=1
```

或使用仓库外部的用户私有文件：

```bash
mkdir -p ~/.config/qexec
cat > ~/.config/qexec/longport-live.env <<'EOF'
export LONGPORT_APP_KEY=...
export LONGPORT_APP_SECRET=...
export LONGPORT_ACCESS_TOKEN=...
export QEXEC_ENABLE_LIVE=1
EOF
```

也可以通过 `UV_SYNC_ARGS` 显式覆盖，例如：

```bash
UV_SYNC_ARGS="--group dev --extra cli --extra longport --extra ibkr"
```

## 本地 YAML

复制模板：

```bash
cp config/template.yaml config/config.yaml
```

当前执行引擎主要读取这些字段：

- `broker`
- `execution`
- `fees`
- `fractional_preview`
- `fx`

示例：

```yaml
broker:
  backend: null
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

也兼容这种汇率结构：

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
- `LONGPORT_TRADING_WINDOW_START/END` 只是会话 API 不可用时的本地降级判断。
- `LONGPORT_MAX_QTY_PER_ORDER` 和 `LONGPORT_MAX_NOTIONAL_PER_ORDER` 更偏兼容层 / 遗留客户端语义。当前主执行路径仍以 `execution.risk.*` 作为主要风控来源。
- `execution.kill_switch.env_var` 和可选 `execution.kill_switch.path` 可以手动停掉新的券商提交。
- `broker.default_account` 是 CLI 没显式传 `--account` 时的默认标签；如果适配器不支持该标签，会直接报错。
- `execution.state_dir` 控制幂等与恢复状态文件目录，默认是 `outputs/state`。
- 盈透证券目前依赖本地已启动的 IB Gateway，当前配置层只开放模拟盘运行路径，暂不支持切换到实盘券商后端。
