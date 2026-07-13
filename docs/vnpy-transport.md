# vn.py Gateway / OMS Transport

`quant_execution_engine.vnpy_transport` 是 `ExecutionTransport` 的可选 vn.py 实现。它复用 vn.py
的 Gateway 下单、撤单、EventEngine callback 和 OMS 合约缓存，同时把审批、policy、preflight、
幂等、持久 journal、对账和审计继续留在 qexec。

安装可选依赖：

```bash
uv sync --group dev --extra cli --extra vnpy
```

核心包、现有 CLI 和其他 broker adapter 不依赖 vn.py。`vnpy_transport` 本身也只在构造 adapter
时从 leaf loader 延迟导入 vn.py；未安装时会给出明确的 extra 安装提示。

本仓只提供 bridge，不捆绑任何具体 vn.py broker Gateway。Gateway 包、连接配置、账户权限和人工
演练证据必须单独管理。当前 `qexec rebalance` 默认路径也没有切换到该 bridge。

## 三种模式

| 模式 | 默认能力 | 运行时保护 |
| --- | --- | --- |
| `SHADOW` | 只允许 contract preview 和 callback polling | capability 声明禁止 submit/cancel，方法内部再次拒绝 `send_order` / `cancel_order` |
| `PAPER` | 允许 fake 或模拟盘 Gateway submit/cancel，允许 event/fill polling | 仍要求 durable journal 的一次性提交许可 |
| `LIVE` | 默认禁止 submit/cancel | 只有显式构造 `allow_live=True` 才在 capability 和运行时两层开放 mutation |

adapter 默认是 `SHADOW`。`allow_live=True` 在非 `LIVE` 模式会直接报错，避免一个看似无害的参数
被复制到错误环境。

无论哪种模式，`OrderIntent.broker_name` 都必须与 transport canonical backend name 完全一致。
这可以防止已批准给一个 Gateway 的 intent 被误送到另一个 Gateway。

## 映射边界

adapter 使用真实 vn.py 4.x 类型完成 leaf 内映射：

```text
qexec OrderIntent
  -> vn.py ContractData validation
  -> vn.py OrderRequest
  -> MainEngine.send_order(gateway_name)

vn.py OrderData / TradeData event
  -> qexec OrderEvent / Fill
  -> JournaledExecutionTransport.poll_and_record
  -> DurableExecutionJournal
```

vn.py SDK 对象不会成为 `TransportSubmission`、artifact、journal 或跨仓库 contract 的字段。
`preview_order` 返回的是 qexec 自己的不可变 `VnPyOrderPreview`，实际 `OrderRequest` 只传给
`MainEngine.send_order`。

当前 common mapping 为：

- BUY / SELL -> `Direction.LONG` / `Direction.SHORT`；股票类合约使用 `Offset.NONE`；
- MARKET / LIMIT / STOP -> vn.py 同名 order type；STOP 还要求 `ContractData.stop_supported`；
- LIMIT + IOC -> `OrderType.FAK`；LIMIT + FOK -> `OrderType.FOK`；
- common `OrderRequest` 无可靠 GTC 字段，因此 GTC、STOP_LIMIT、TRAILING_STOP 明确不支持；
- quantity 必须满足 `ContractData.min_volume`；碎股和开空能力由显式 `VnPyGatewayProfile` 声明；
- 默认只开放 `EQUITY`、`ETF`、`FUND`，其他 product 必须在 profile 中明确加入。

合约必须已存在于 vn.py OMS contract cache。没有 exchange 时只允许同一 Gateway 下 symbol 唯一的
合约；存在歧义时要求调用方补 exchange。capability notes 会报告 contract cache 来源和当前数量，
但不把“缓存中有一个合约”夸大成券商连接或账户权限已经就绪。

## EventEngine、OMS 与对账限制

bridge 注册 vn.py `EVENT_ORDER` 和 `EVENT_TRADE` handler，接收真实 `OrderData`、`TradeData`，并
产生稳定的 qexec event/fill ID。重复 callback 可以重复进入 batch，由 durable journal 幂等去重；
乱序 callback 由 journal reducer 保证 `FILLED`、`PARTIALLY_FILLED` 等状态不会倒退。

vn.py `OmsEngine.get_order/get_all_orders` 是进程内 callback cache，不是可靠的券商查询 API。因此
本 transport 明确声明：

- `supports_query=False`；
- `supports_client_order_lookup=False`；
- `query()` 抛出 `UnsupportedTransportCapabilityError`，不会把 OMS cache 伪装成对账结果。

accepted-but-timeout、进程重启或 callback 缺失时，必须使用具体 Gateway 提供的可靠查询能力、独立
adapter 或人工券商侧证据完成 reconciliation。在此能力存在前，不应把 vn.py bridge 设为 qexec
默认 live runtime。

## 生命周期

adapter 构造时可注册 order/trade handler，`close()` 会幂等注销。默认认为 `MainEngine` 由外部
应用持有，不主动关闭；只有显式 `owns_main_engine=True` 才调用 `MainEngine.close()`。这样不会让
一个临时 transport 意外关闭同进程中的其他 vn.py App 或 Gateway。

自动化测试使用 fake MainEngine/Gateway 和真实 vn.py `OrderRequest`、`CancelRequest`、
`ContractData`、`OrderData`、`TradeData`，不连接任何券商，也不读取凭证。

