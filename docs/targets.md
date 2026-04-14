# 持仓指令清单格式

## 约束

execution-engine 只接受 schema-v2 `targets.json`。

每个 target 必须包含：

- `symbol`
- `market`

每个 target 必须二选一：

- `target_weight`
- `target_quantity`

可选字段：

- `notes`
- `metadata`

## 最小示例

```json
{
  "schema_version": 2,
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

## 字段说明

- `schema_version`
  当前 canonical 版本，live execution 要求为 `2`。
- `asof`
  目标生成日期，通常来自上游 research repo。
- `source`
  产出来源，例如 `research-core`。
- `target_gross_exposure`
  目标总暴露倍率，默认 `1.0`。
- `targets`
  目标列表。
- `notes`
  可选备注。

每个 target entry 还支持：

- `notes`
  单个标的备注。
- `metadata`
  透传的扩展字段。

## 市场标识

当前支持：

- `US`
- `HK`
- `CN`
- `SG`

如果 `symbol` 自带 `.US` / `.HK` / `.CN` / `.SG` 后缀，会自动解析对应市场；未提供市场时默认按 `US` 处理。

## 兼容行为

- `write_targets_json()` 仍可接受 legacy ticker list，并自动规范化成 schema-v2。
- `read_targets_json(require_schema_v2=True)` 会拒绝 legacy 输入。
- live execution 路径始终使用 `require_schema_v2=True`。
