# Configuration

## 环境变量

必需：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

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

## 本地 YAML

复制模板：

```bash
cp config/template.yaml config/config.yaml
```

当前 execution-engine 只读取这些字段：

- `fees`
- `fractional_preview`
- `fx`

示例：

```yaml
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
