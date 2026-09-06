# `targets.json` 格式

`qexec rebalance` 只接受带有顶层 `targets` 数组的 JSON 文件。每个目标表达一个标的的目标权重或目标数量。

## 推荐格式

```json
{
  "asof": "2026-04-09",
  "source": "strategy-pipeline",
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

每个目标必须提供 `symbol`，并在 `target_weight` 与 `target_quantity` 中选一个。两个仓位字段同时提供或同时缺失都会被拒绝。

推荐始终写明 `market`。这样便于上游审计，也能减少无后缀代码的歧义。

## 顶层字段

| 字段 | 是否必需 | 当前语义 |
| --- | --- | --- |
| `targets` | 是 | 非空目标数组 |
| `asof` | 否 | 目标生成日期或数据截面时间 |
| `source` | 否 | 上游来源标识 |
| `target_gross_exposure` | 否 | 总敞口倍率，默认 `1.0`，不得小于零 |
| `notes` | 否 | 整份目标清单的备注 |
| `schema_version` | 否 | 记录在解析结果中的版本元数据，见下文 |

目标项还可包含 `notes` 和 `metadata`。`metadata` 会进入目标对象，执行计划仍由标的、市场、仓位字段和执行侧风控决定。

## 市场和代码推断

支持的市场代码为 `US`、`HK`、`CN` 和 `SG`。`A_SHARE`、`ASHARE`、`CN_A` 会归一为 `CN`。

解析顺序如下：

1. 显式 `market` 优先。
2. 缺少 `market` 时，`.US`、`.HK`、`.CN`、`.SG` 后缀用于推断市场。
3. `.SH`、`.SZ`、`.BJ`、`.XSHG`、`.XSHE` 后缀用于推断 `CN`。
4. 市场和后缀都缺失时，`qexec` 当前按 `US` 解析。

A 股目标应保留交易所后缀：

```json
{
  "targets": [
    {"symbol": "600519.SH", "market": "CN", "target_weight": 0.5},
    {"symbol": "000858.SZ", "market": "CN", "target_weight": 0.3},
    {"symbol": "430047.BJ", "market": "CN", "target_weight": 0.2}
  ]
}
```

`.XSHG` 会归一为 `.SH`，`.XSHE` 会归一为 `.SZ`。带这些交易所后缀的纯数字代码会补足六位。仅有数字和 `market: CN` 时无法推断交易所，也不会自动补后缀。文件中的推荐形式是 `600519.SH` 配合 `market: CN`。长桥适配层会在运行时转换为 `600519.SH.CN`。

## `schema_version` 的当前语义

目标文件写入工具当前省略 `schema_version`。读取器在字段缺失或无法转成整数时记录默认值 `2`。如果文件提供其他整数，读取器会原样记录，目前不会据此拒绝调仓。

因此，目标文件里的 `schema_version` 目前属于描述性元数据，尚未形成版本兼容门禁。类型化执行领域的 v2 wire codec 使用另一套严格版本检查，规则见 [typed-execution-domain.md](typed-execution-domain.md)。

## 输入边界

- 旧的顶层 `tickers` 和 `weights` 格式不能直接进入调仓命令。
- 内部工装可以接收 ticker 列表，再写成标准 `targets` 数组。
- `rebalance` 以 USD 统一估值。目标或现有持仓包含 `HK`、`CN`、`SG` 时，需要配置对应的 `FX_<CCY>_USD` 或 `fx.to_usd.<CCY>` 汇率。
- 上游可以在 `targets.json.lineage.json` 记录策略、信号产物和运行来源。sidecar 不参与下单参数计算。

研究候选进入执行层前的证据边界见 [research-handoff-governance.md](research-handoff-governance.md)。
