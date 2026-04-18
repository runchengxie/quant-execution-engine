# 目标持仓清单（targets.json）格式说明

## 格式约束

本执行引擎仅接受符合规范的 `targets.json` 文件作为调仓指令的输入。

清单列表中的每个目标对象（Target）必须包含以下核心字段：

- `symbol`（标的代码）
- `market`（所在市场）

此外，在表达预期仓位时，每个目标对象必须且只能在以下两个字段中选择其一（不可同时为空，也不可同时提供）：

- `target_weight`（目标权重）
- `target_quantity`（目标数量）

系统支持的额外可选字段包括：

- `notes`（备注信息）
- `metadata`（扩展元数据）

## 最小配置示例

```json
{
  "asof": "2026-04-09",
  "source": "research-core",
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

## 字段详细说明

### 全局字段

- `asof`
  目标清单的生成日期或对应的数据截面时间（通常由上游的策略研究端提供）。
- `source`
  指令的产出来源标识，例如 `research-core`。
- `target_gross_exposure`
  目标总风险敞口倍率，默认值为 `1.0`。
- `targets`
  具体的标的持仓目标列表。
- `notes`
  针对整份清单的全局备注说明（可选）。

### 目标项（Target）专属字段

针对 `targets` 列表中的每一项，除核心必填字段外，还支持以下可选字段：

- `notes`
  针对单个交易标的的备注信息。
- `metadata`
  用于向下游执行链路透传的扩展参数或自定义元数据。

## 市场标识（Market）说明

引擎目前原生支持以下四个市场标识：

- `US`（美股）
- `HK`（港股）
- `CN`（A股）
- `SG`（新加坡股）

解析规则：
如果在生成目标时，传入的 `symbol` 自带诸如 `.US`、`.HK`、`.CN`、`.SG` 等后缀，系统会自动提取并解析出对应的市场代码；如果在输入数据中完全未指定市场标识，系统将默认将其按照美股（`US`）处理。

## 输入边界

调仓入口只接受上面这种包含 `targets` 数组的标准目标清单。

- 每个目标项必须提供 `symbol`、`market`，并且只能在 `target_weight` 与 `target_quantity` 中选择一个。
- 旧的 ticker-list / weights 形状不是调仓执行输入。
- 内部工装如果接收 ticker 列表，会先写成上述标准 JSON，再交给执行链路。
