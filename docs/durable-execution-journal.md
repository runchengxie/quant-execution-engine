# 持久执行 Journal

`quant_execution_engine.execution_journal` 提供一个新增的、框架中立的执行生命周期
journal。它建立在 QE-01 的不可变 `OrderIntent`、`OrderEvent` 和 `Fill` 之上，不导入券商
SDK，也不改变当前 CLI 使用的 v1 JSON 状态文件。

## 安全边界

一次可能访问券商的流程必须先调用：

```python
prepared = journal.prepare_submission(
    intent,
    idempotency_key="portfolio/account/run/target-row",
    attempt_id="stable-attempt-id",
)
if prepared.should_submit:
    broker.submit(intent)
```

`prepare_submission` 在同一个 `BEGIN IMMEDIATE` 事务中写入 intent、幂等键和
`SUBMISSION_STARTED` 事实。事务使用 `synchronous=FULL`；方法返回前，这些记录已经提交。
返回 `should_submit=True` 的调用方是唯一获准调用 transport 的调用方。

`SUBMISSION_STARTED` 会立即归约为 `SUBMISSION_UNCERTAIN`，而不是乐观地记成“尚未提交”。
原因是进程可能在券商接受请求之后、保存响应之前退出。重启或并发调用使用相同 intent / 幂等键
时会得到 `should_submit=False`，必须先查询券商并追加 `OrderEvent` 或
`ReconciliationEvidence`，不能盲目重报。这个保守状态也覆盖了“本地提交许可已落盘、但进程在
真正调用券商前退出”的情况；它宁可产生一次需要人工确认的假阳性，也不冒重复下单风险。

同一个幂等键只能对应完全相同的 canonical intent。同一个 intent ID 或稳定 record ID 被用于
不同内容时，journal 会抛出 `IdempotencyConflictError`，整个事务回滚。

## 持久化和归约

SQLite store 使用：

- WAL journal mode、`synchronous=FULL` 和写事务串行化；
- 只追加的 event、intent index 和 snapshot 表；
- 阻止 UPDATE / DELETE 的数据库 trigger；
- 覆盖序号、前序 hash、事件类型、时间和 payload 的全局 SHA-256 hash chain；
- canonical JSON 和 timezone-aware UTC 时间；
- `PRAGMA quick_check`、payload hash 和 snapshot hash 的失败关闭校验。

当前状态不是独立写入的事实源，而是由 journal entry 纯函数归约得到。重复的 broker callback、
fill 和 reconciliation evidence 以稳定 ID 幂等去重；同一个 ID 的不同内容会失败。过时的
`ACCEPTED` callback 不能把 `PARTIALLY_FILLED` 降级，迟到的 `CANCELLED` 也不能把
`FILLED` 降级。迟到的完整成交可以把先前的取消终态修正为 `FILLED`，原始事件仍全部留在
审计链中。

`create_snapshot` 追加一个不可变的 materialized checkpoint。`replay()` 会先验证完整数据库
和全局 hash chain，再从最新 snapshot 加载状态并归约后续记录；`replay(use_snapshot=False)`
可作为 snapshot 损坏时从原始事件恢复的显式入口。

## 对账证据

`ReconciliationEvidence` 保存一次带时区的券商观察，包括来源、订单状态、累计成交量、剩余量、
broker order ID 和 JSON metadata。证据与订单回报使用相同的追加、hash 和幂等约束，并进入
snapshot，因此重启前后可以得到相同状态和相同证据序列。

## 当前迁移状态

本 PR 只提供新 API 和恢复证据：

- 当前 `rebalance`、恢复命令和 broker adapter 仍使用 `execution_state.py` 的 v1 文件；
- 不会自动创建 journal 数据库，也不会改变当前报单路径；
- 后续 transport adapter 必须把 `prepare_submission` 作为唯一提交许可点，并在 parity 和故障
  测试通过后才可切换默认路径；
- 回滚本 PR 只需停止调用新 API；现有 v1 状态和 CLI 无需迁移。

当前实现假设数据库位于支持 SQLite 锁和 fsync 语义的本地文件系统，不支持把活动数据库直接放在
语义不明的网络文件系统。一个 intent 只允许一次 broker submission attempt；撤改单、人工重试或
新的订单意图应使用新的 intent 和幂等键。读取时仍会校验完整 hash chain，因此 snapshot 主要减少
归约成本，不是日志压缩机制。
