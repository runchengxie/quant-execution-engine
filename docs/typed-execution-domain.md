# 类型化执行领域边界

`quant_execution_engine.domain` 是执行状态、日志和传输层使用的框架中立领域边界。当前 CLI 继续使用 `models.py` 中的数据对象，v1 文件状态继续由 `execution_state.py` 维护。

## 领域链路

```text
PortfolioTarget
  -> ApprovedTarget
  -> OrderIntent
  -> OrderEvent / Fill
```

- `PortfolioTarget` 表达研究侧目标，不直接表达券商报单。
- `ApprovedTarget` 保存执行政策和账户范围内的批准结果。
- `OrderIntent` 表达一次类型化报单意图。
- `OrderEvent` 与 `Fill` 表达券商边界返回的不可变事实。

所有领域对象都是不可变 dataclass。数量、价格和金额使用 `Decimal`。时间使用带时区的 `datetime`。方向、订单类型、有效期、状态和事件类型使用字符串枚举。
这些模块不导入任何券商 SDK、Qlib、LEAN 或 vn.py 类型。

## 能力验证

负目标和碎股目标是合法领域值，不再由基础类型假设 long-only 或整数股。执行前使用
`ExecutionCapabilities` 和以下验证入口判断具体后端是否支持：

- `validate_portfolio_target_capabilities`
- `validate_order_intent_capabilities`

卖出订单不等同于做空订单。`OrderIntent.opens_short` 显式表达是否新开空头，避免平多卖单
被错误地按照做空能力处理。

## v1 兼容与 v2 编解码

`quant_execution_engine.serialization` 提供显式迁移入口：

- `portfolio_target_from_v1`
- `order_intent_from_v1`
- `order_event_from_v1`
- `fill_from_v1`

该模块是稳定的公开入口。通用 wire 基础类型、v1 迁移和 v2 编解码分别位于三个私有实现模块，调用方不应直接依赖这些私有模块。

旧格式允许无时区时间。迁移时必须通过 `naive_timezone` 明确解释该时间，默认值为 UTC。v2 读取器遇到无时区时间会拒绝读取。

v2 wire 映射规则：

- `schema_version` 固定为 `2`，并包含明确的 `kind`
- 所有 `Decimal` 以规范化十进制字符串写入 JSON
- 所有时间统一写成 UTC ISO-8601（`Z` 后缀）
- `dumps_v2` 使用排序键和紧凑分隔符，输出可重复的规范 JSON
- 框架和 SDK 对象不得进入 `metadata` 或 wire payload

v2 编解码只处理 qexec 领域对象，不改变当前 `targets.json` 的默认写法。现有 CLI 和状态文件继续使用 v1 路径，后续迁移需要独立的兼容与恢复证据。
