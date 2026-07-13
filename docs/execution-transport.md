# 类型化执行 Transport

`quant_execution_engine.transport` 定义框架中立的机械执行边界；
`broker_transport` 把现有 qexec broker adapter 包装到该边界；`paper_transport` 提供完全离线的
内存模拟实现；`transport_service` 负责把 transport 与 durable journal 连接起来。

这是一条新增的 additive API。当前 `qexec rebalance`、policy、preflight、risk 和 v1 JSON 状态
仍走原有路径，默认行为没有切换。

## 责任边界

```text
approval / policy / preflight / risk
                  |
                  v
             OrderIntent
                  |
       DurableExecutionJournal.prepare_submission
                  |
          should_submit == true
                  |
                  v
          ExecutionTransport
                  |
        OrderEvent / Fill callbacks
                  |
                  v
       DurableExecutionJournal append/replay
```

transport 只能：

- 发现 submit、cancel、query、poll 和 client-order lookup 能力；
- 把类型化 `OrderIntent` 机械映射为券商请求；
- 把券商订单、callback 和成交归一化为 `OrderEvent` / `Fill`；
- 明确拒绝未声明支持的操作。

transport 不得：

- 决定目标是否获批；
- 执行组合、策略或风险政策；
- 绕过 preflight 或 kill switch；
- 把 SDK、vn.py 或其他框架对象写进跨仓库 contract 或 journal。

## 唯一提交许可

`TransportSubmitRequest` 必须携带 `DurableExecutionJournal.prepare_submission` 返回且
`should_submit=True` 的 `SubmissionPreparation`。推荐只通过 `JournaledExecutionTransport.submit`
调用：

```python
executor = JournaledExecutionTransport(transport, journal)
outcome = executor.submit(
    approved_intent,
    idempotency_key="portfolio/account/run/target-row",
    attempt_id="stable-attempt-id",
)
```

能力验证在写入提交许可前完成，因此不支持的 order type、TIF、碎股、做空或 submit 操作不会消耗
许可。`OrderIntent.broker_name` 还必须与 transport 的 canonical backend name 完全一致，避免把
已经批准给一个账户通道的 intent 误送到另一个通道。许可落盘后，任何 transport 异常都按“券商
结果未知”处理：追加
`SUBMISSION_UNCERTAIN` 原因并抛出 `SubmissionOutcomeUnknownError`。同一 intent / 幂等键重启后
得到 `should_submit=False`，不会盲目重报。

若券商已接受但响应丢失，可使用 `TransportOrderReference.from_intent(intent)` 通过稳定的
`client_order_id` 查询支持该能力的后端，再由 `query_and_record` 追加实际订单状态。不能按 client
order ID 查询的 transport 会明确失败并要求人工/券商侧对账。

## 当前实现

### `BrokerAdapterExecutionTransport`

该 adapter 复用现有 Alpaca paper、IBKR paper、LongPort paper/live 和 local-dry-run 的能力矩阵
与标准化 record。它不改变这些 broker adapter，也不接管当前 CLI。

- 声明 `supports_live_submit` 或明确 `submit_mode=paper` 的后端可映射 submit；
- query、cancel、open-order/client-ID lookup 按现有 capability matrix 暴露；
- 同一个 broker snapshot 会生成稳定 event ID，重复 poll 可由 journal 幂等去重；
- 只有 open-order listing、没有历史查询的后端，其 client-ID 恢复能力明确标记为
  `open-orders-only`；终态订单仍可能需要人工或券商侧对账；
- 不支持的能力抛出 `UnsupportedTransportCapabilityError`，不会静默降级；
- `local-dry-run` 可被包装用于能力发现，但它仍禁止真实 submit。

### `InMemoryPaperExecutionTransport`

这是无网络、无凭证的内存 transport。submit 只产生 `ACCEPTED`；不会假装成交。测试或离线模拟器
必须显式调用 `record_fill` 注入成交，然后通过 `poll_and_record` 写入 journal。它适合 contract、
幂等、恢复和上层编排测试，不是交易所撮合仿真器。

### `VnPyExecutionTransport`

可选 vn.py bridge 已作为独立 leaf adapter 提供，但不改变默认路径。它复用 Gateway/EventEngine，
默认 `SHADOW`，并明确拒绝把内存 OMS cache 当成可靠 broker query。详细边界见
[vnpy-transport.md](vnpy-transport.md)。

八类 timeout、重复/乱序 callback、重启和对账故障由独立的纯离线 evidence path 覆盖；它复用
本 transport contract 与 durable journal，不改变默认执行路径。见
[execution-recovery-matrix.md](execution-recovery-matrix.md)。

## 迁移与回滚

- 当前 v1 CLI 和 `OrderLifecycleService` 保持默认，不从本 API 自动报单；
- vn.py 仅属于 `vnpy` optional extra，核心 transport 与现有 CLI 不导入它；
- 切换默认路径前需要 paper/shadow parity、故障注入和操作员证据；
- 回滚只需停止调用 additive transport API，原有 broker adapter、CLI 和 v1 state 不需迁移。
