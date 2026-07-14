# AFML 动态执行策略与研究交接审计

本页记录执行层新增的动态目标、平均限价、参与率约束和研究交接审计。执行层继续只消费经过批准的目标和市场输入，不根据 Sharpe、IC、PBO 或模型解释改变标的和目标权重。

## 动态目标和平均限价

`quant_execution_engine.execution_policy` 提供：

- sigmoid bet size
- sigmoid 宽度校准
- target size 对应价格的反函数
- 从当前仓位到目标仓位的精确平均逆函数限价
- lot-size 离散化
- recent-volume participation cap
- execution policy receipt

```python
from quant_execution_engine.execution_policy import (
    DynamicLimitConfig,
    build_dynamic_execution_decision,
    calibrate_sigmoid_width,
)

omega = calibrate_sigmoid_width(
    price_divergence=10.0,
    target_size=0.95,
)

decision = build_dynamic_execution_decision(
    current_price=100.0,
    forecast_price=110.0,
    current_quantity=0,
    omega=omega,
    config=DynamicLimitConfig(
        max_position=1000,
        lot_size=100,
        max_participation_rate=0.05,
    ),
    recent_market_volume=4000,
)
```

该函数输出原始目标、离散目标、订单数量、参与率限制后的数量和平均限价。它不直接提交订单。券商 adapter 接入前还需定义价格 tick、订单有效期、行情新鲜度和市场特定涨跌停限制。

## 研究交接审计

`quant_execution_engine.handoff_audit` 只检查：

- `targets.json` 最小 schema
- 重复 target
- lineage 是否存在
- targets hash
- release protocol status/hash
- sizing receipt hash
- strategy-risk receipt hash

运行：

```bash
python -m quant_execution_engine.handoff_audit \
  outputs/targets/2026-07-14.json \
  --require-release-protocol \
  --output outputs/evidence/handoff-audit-2026-07-14.json
```

审计不会读取研究指标并重新计算订单。即使 lineage 记录了 Sharpe、IC 或 DSR，它们也只属于证据包。

## 接入原则

- 动态执行策略必须由显式 broker/policy 配置启用。
- dry-run 和 paper 路径先于 live。
- 每个策略决策写入 receipt，并关联 targets hash。
- 缺少 recent volume 时可以保留原订单数量，但必须由上层风控决定是否允许降级。
- 非法或过期 forecast price 必须在 preflight 阶段拒绝。
- 研究协议负责允许目标进入执行；执行风控仍可独立拒绝目标。
