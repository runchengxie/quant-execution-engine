# 执行恢复故障矩阵

`qexec recovery-matrix` 使用本地 `InMemoryPaperExecutionTransport`、临时 SQLite journal 和固定时间、
价格、数量运行八个故障场景，生成 `execution_recovery_matrix.v1` 证据。它用于验证执行状态归约、
幂等许可和恢复决策，不连接券商，也不替代真实账户对账。

```bash
qexec recovery-matrix \
  --mode shadow \
  --output outputs/evidence/execution_recovery_matrix.v1.json
```

`shadow` 和 `paper` 都只是证据标签：两种模式均只调用仓库内的 fake/in-memory transport，不构造
vn.py `MainEngine`、Gateway 或任何直接 broker adapter，不读取凭证，也不发起网络连接。默认使用
`shadow`。

## 证据合同

输出是 canonical UTF-8 JSON：键排序、两空格缩进、Decimal 使用无多余零的字符串、末尾恰好一个
换行。重复运行同一 mode 会得到完全相同的 bytes 和 SHA-256。合同严格拒绝未知字段，顶层只有：

```json
{
  "schema": "execution_recovery_matrix.v1",
  "mode": "shadow",
  "deterministic": true,
  "live_broker_access": false,
  "scenarios": []
}
```

`scenarios` 固定按以下顺序出现。每项都包含 `id`、`status=passed`、结构化 `expected_state` 和
`reconciliation`。只有场景断言、journal 完整性、幂等性和状态单调性全部满足后，才会写入
`passed`。

| 场景 | 预期状态 | 对账结论 |
| --- | --- | --- |
| `accepted_but_timeout` | 首次提交保持 uncertain，重复提交不再触达 transport，broker fact 到达后恢复 `ACCEPTED` | 找到原订单，继续 callback polling，禁止盲目重提 |
| `duplicate_submission` | transport submit 总次数保持 1 | 复用 durable idempotency 结果 |
| `duplicate_callback` | 同 ID 的 order/fill 只记一次，保持 `PARTIALLY_FILLED` | duplicate facts 被幂等去重 |
| `out_of_order_callback` | stale accepted/cancel 不得把 partial/filled 状态倒退 | 保留全部回报证据，最终 `FILLED` |
| `partial_fill_restart` | snapshot 与 raw replay 一致，重启后仍是 `PARTIALLY_FILLED`，不重提 | 操作员选择 cancel-rest 或 resume-remaining |
| `cancel_fill_race` | cancel ack 后的迟到成交仍可把状态升级到 `FILLED` | 成交事实优先，同时保留撤单证据 |
| `reconnect_replay` | 重连补推相同 callback 不改变 sequence 或 state | 恢复 callback polling |
| `position_drift` | journal 订单事实不被账户漂移覆盖 | 要求 kill switch 与人工持仓对账 |

`position_drift` 使用固定的本地期望持仓 10 和 fake broker 持仓 7，证据中记录 `position_drift=-3`。
这只是对账决策 fixture，不会写入或伪造真实账户持仓。

## 操作员恢复顺序

当生产系统出现 accepted_but_timeout、重连补推异常、撤单成交竞态或持仓漂移时：

1. 立即停止新增提交。启用当前配置指定的手动 kill switch，默认可使用
   `export QEXEC_KILL_SWITCH=1`。
2. 运行 `qexec config --check-gates` 和 `qexec preflight`，确认 manual/state kill switch 已阻止
   新提交。kill switch 不应阻止只读查询、诊断和必要的撤单。
3. 不得对 `SUBMISSION_UNCERTAIN` intent 盲目 retry。先从券商侧只读查询 order、fill、position，
   使用 client order ID、broker order ID、账户和 instrument 交叉核对。
4. 保存 broker receipt、callback、journal integrity 结果和 position snapshot，再执行 reconcile。
   本地 cache 不能代替券商权威查询。
5. 部分成交时，根据已确认的 open remainder 选择 `cancel-rest`、`resume-remaining` 或
   `accept-partial`。撤单与成交并发时，以最终 fill 总量为准。
6. 持仓、现金、open orders 和 journal 全部一致，并经第二人复核后，才可解除 kill switch。
   对环境开关执行 `unset QEXEC_KILL_SWITCH`；若本地 state kill switch 也已激活，先备份状态并运行
   `qexec state-doctor`，确认原因消除后才使用 `qexec state-repair --clear-kill-switch`。
7. 再次运行 preflight，并从 shadow/paper 小批量恢复。不得直接跳回无监督 live 执行。

## 回滚边界

本功能是 additive evidence path，未接入当前 rebalance 默认执行链。代码回滚只需停止调用
`recovery-matrix` 并移除该命令；不需要迁移或删除现有 v1 state、durable journal 或 broker 配置。
发生生产事故时，“回滚”不等于删除 journal、清理 unknown intent 或重置 idempotency key；这些记录
必须保留到券商事实和账户持仓完成对账。

故障矩阵不会自动设置或清除真实 kill switch，也不会自动撤单、补单或修正持仓。它输出的是可供
workspace validator 和操作员审阅的确定性恢复证据，而不是实盘操作授权。
