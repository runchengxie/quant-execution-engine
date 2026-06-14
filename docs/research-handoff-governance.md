# 研究到执行交接治理

本页说明执行引擎怎样接收上游研究结果，以及哪些边界用于避免执行阶段反向污染研究验证。策略研究、防过拟合评估、历史回测、CPCV、DSR 和候选晋升都在上游研究仓库完成；本仓库只处理标准目标持仓、风控、执行、对账和审计。

## 执行侧承担的防线

| 风险 | 执行侧机制 | 主要证据 |
| --- | --- | --- |
| 非标准研究输出直接下单 | `rebalance` 只接受标准 `targets.json` | `docs/targets.md`、目标文件解析错误 |
| sidecar 元数据影响下单 | lineage sidecar 只用于审计和复现，订单计划只由 `targets.json` 与执行侧风控决定 | `targets.json.lineage.json`、审计日志 |
| 调参后的结果直接进入实盘 | dry-run、paper、real 分层，实盘需要显式保护开关和人工监督 | `QEXEC_ENABLE_LIVE=1`、smoke 文档、evidence bundle |
| 执行状态丢失 | 本地订单状态和对账维护母订单、子订单、成交事件 | `outputs/state/*.json`、`qexec reconcile` |
| 无证据执行 | 调仓审计日志和 evidence bundle 留存目标文件、状态和操作员备注 | `outputs/orders/*.jsonl`、`outputs/evidence-bundles/*` |
| 风控数据缺失被静默忽略 | 风控检查输出通过、拦截或跳过，并记录降级原因 | preflight / rebalance 结构化输出 |

这些机制不能证明策略没有过拟合。它们证明的是：进入执行的目标清单格式稳定、执行链路可复查、paper/live 边界清晰，且实盘动作受独立门禁控制。

## 上游输入要求

执行引擎只要求输入满足文件契约：

```text
targets.json
targets.json.lineage.json
```

`targets.json` 必须包含标准 `targets` 数组，每个目标项提供 `symbol`、`market`，并且只能在 `target_weight` 与 `target_quantity` 中选择一个。详细格式见 `targets.md`。

`targets.json.lineage.json` 可记录上游 run、strategy、signal artifact、配置哈希、研究证据路径或人工备注。执行引擎会把它作为审计材料看待，不把其中的 Sharpe、IC、promotion status 或候选说明作为下单依据。

## 从研究证据到执行动作

建议把上游候选到执行动作分成四层：

1. 研究侧完成数据、特征、walk-forward、final OOS、CPCV、DSR 和 promotion gate 证据。
2. 研究侧导出冻结后的 `targets.json` 和 `targets.json.lineage.json`。
3. 执行侧先运行 `qexec rebalance <targets.json>` 做 dry-run 和风控预览。
4. 需要真实券商路径时，先走模拟盘；实盘必须按对应 smoke 文档和实盘保护开关执行。

执行引擎不会回看上游训练样本，也不会根据执行结果自动修改模型、特征或候选配置。paper/live 的执行结果可以作为后续人工复核证据，由研究侧另行决定是否进入新一轮研究。

## 推荐检查

在接受一个新研究候选进入执行前，操作员至少应确认：

- `targets.json` 来自上游正式导出命令，而非手工拼接。
- lineage sidecar 能追溯到具体 run、config 和持仓文件。
- 上游研究文档已经说明 final OOS、CPCV、feature evidence、DSR 或其替代证据。
- `qexec rebalance` dry-run 能生成可解释的调仓计划。
- 非 USD 市场目标已经配置必要 FX。
- 执行前风控没有被未知原因跳过；如有跳过，审计日志中有明确降级原因。
- 模拟盘证据足够后，实盘仍按 `current-capabilities.md` 和对应 smoke 文档单独放行。

## 相关文档

- `targets.md`：执行输入文件格式。
- `current-capabilities.md`：券商能力矩阵、成熟度和已知限制。
- `execution-foundation.md`：订单生命周期、本地状态、对账、风控和恢复链路。
- `testing.md`：测试分层、冒烟测试和 evidence bundle。
