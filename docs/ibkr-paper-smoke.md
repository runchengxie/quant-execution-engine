# IBKR 模拟盘冒烟测试

这份文档的目标：

- 为 `ibkr-paper` 提供一套最小化的 operator-supervised 模拟盘操作手册
- 明确本地 `IB Gateway + TWS API` 是运行前提，不把 IBKR 误写成纯云端 broker
- 给 `config / preflight / account / quote / rebalance --execute / reconcile` 提供一条可复查的 paper smoke 路径

## 1. 当前边界

当前 `ibkr-paper` 的范围刻意收敛：

- 只支持模拟盘，不支持实盘
- 当前只支持 US equities 最小切片
- 当前仍按单账户语义运行，`--account` 只接受 `main`
- 当前工作区截至 2026-04-16 已有一次 operator-supervised WSL -> Windows Gateway evidence 样例：`outputs/evidence/ibkr-paper-smoke.json`
- 该样例证明 Gateway/account/reconcile 路径可达，但 AAPL 行情因 IBKR competing live session 返回 0，未产生 broker order；提交、成交、撤单证据仍需下一次有有效行情的 paper smoke 补齐

## 2. 运行前提

至少准备这些：

- 本地已安装并可启动的 IB Gateway
- 一个可登录的 IBKR paper 账户
- 已在 Gateway 里启用 TWS API / socket API

可选运行参数：

```bash
export IBKR_HOST="127.0.0.1"
export IBKR_PORT_PAPER="4002"
export IBKR_CLIENT_ID="1"
# 可选；如果 Gateway 下只有一个账户，可以不设
export IBKR_ACCOUNT_ID="DU123456"
export IBKR_CONNECT_TIMEOUT_SECONDS="5"
```

当前后端会优先读取：

- `IBKR_HOST`
- `IBKR_PORT`，如果没设再读 `IBKR_PORT_PAPER`
- `IBKR_CLIENT_ID`
- `IBKR_ACCOUNT_ID`
- `IBKR_CONNECT_TIMEOUT_SECONDS`

## 3. Gateway 设置

启动并登录 paper Gateway 后，至少确认这些 API 设置：

- API 已启用
- 监听端口与 `IBKR_PORT` / `IBKR_PORT_PAPER` 一致
- 当前机器可访问该端口，通常是 `127.0.0.1`
- 当前登录的是 paper 会话，而不是 live
- 如果代码跑在 WSL、Gateway 跑在 Windows，优先试 `127.0.0.1:4002`；如果 WSL2 NAT 模式下连不上，再把 `IBKR_HOST` 改成 Windows host IP
- Gateway 不应处于 API read-only mode；否则 IBKR 会弹出写 API 权限提示并拒绝 paper 下单
- IBKR 需要给当前 API 会话返回有效 market data；如果出现 competing live session 导致价格为 0，`rebalance --execute` 会跳过订单并只留下 no-order evidence

如果 `qexec preflight --broker ibkr-paper` 报 host/port 连不上，先排查 Gateway 是否真的在本机启动并监听。

## 4. 先做只读检查

```bash
qexec config --broker ibkr-paper
qexec preflight --broker ibkr-paper
qexec account --broker ibkr-paper
qexec quote AAPL --broker ibkr-paper
```

重点确认：

- `config` 已显示正确的 host / paper port / client ID / account ID
- `preflight` 没有 Gateway connectivity、account resolution 或 quote 失败
- `account` 能返回 paper 账户概览
- `quote` 能拿到 `AAPL.US` 行情

## 5. 最小 targets 文件

```json
{
  "schema_version": 2,
  "asof": "ibkr-paper-smoke",
  "source": "operator-smoke",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_quantity": 1,
      "notes": "minimal ibkr paper smoke"
    }
  ]
}
```

保存为：

```bash
outputs/targets/ibkr-paper-smoke.json
```

## 6. 最小执行流程

### 6.1 先看预演

```bash
qexec rebalance outputs/targets/ibkr-paper-smoke.json --broker ibkr-paper
```

### 6.2 再做 paper 执行

```bash
qexec rebalance outputs/targets/ibkr-paper-smoke.json --broker ibkr-paper --execute
```

### 6.3 立刻跟进查询

```bash
qexec orders --broker ibkr-paper --symbol AAPL
qexec reconcile --broker ibkr-paper
```

如果本地状态里已经拿到已跟踪 broker order ID，再查单笔：

```bash
qexec order <broker-order-id> --broker ibkr-paper
```

如果订单仍然 open，可以验证撤单：

```bash
qexec cancel <broker-order-id> --broker ibkr-paper
qexec reconcile --broker ibkr-paper
```

## 7. 用 smoke harness 跑固定流程

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker ibkr-paper \
  --preflight-only
```

或者直接执行最小 paper workflow 并留证：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker ibkr-paper \
  --execute \
  --evidence-output outputs/evidence/ibkr-paper-smoke.json \
  --operator-note "operator supervised paper smoke"
```

## 8. 这次 smoke 至少要留什么

- 输入的 `targets.json`
- `config / preflight / account / quote / rebalance / reconcile` 的终端输出
- `orders / order / cancel` 的终端输出，如果这次覆盖到了
- `outputs/orders/*.jsonl`
- `outputs/state/*.json`
- `outputs/evidence/ibkr-paper-smoke.json`，如果你用了 harness
- 一段人工备注：运行时间、Gateway host/port、账户、symbol、broker order ID、最终状态、是否覆盖了 cancel / fill
- 如果行情为 0 或 Gateway 阻止写 API，也要在 evidence/operator note 里写明；这类 evidence 可证明 runtime 可达性，但不能替代提交/成交/撤单证据
- `outputs/` 默认被 git 忽略；这里的 evidence 是本地可复查记录，不是随仓库版本化提交的测试夹具。

## 9. 成熟度判断

当前 `ibkr-paper` 不应该被当成“已经像 Alpaca paper 一样成熟”的路径。

更合适的判断标准是：

- 只读检查已稳定
- 最小 `rebalance --execute` 跑通
- `orders / order / reconcile / cancel` 在本地状态上可复查
- 至少有一份 operator-supervised evidence 样例

当前已有第一份样例，但它是 no-order evidence：`config / account / quote / rebalance / reconcile / exceptions / cancel-all` 流程跑完，审计日志也写入 `outputs/orders/20260416-181822_paper_live.jsonl`，但 AAPL quote 为 0，`audit_order_count=0`。

因此现阶段建议把 `ibkr-paper` 视为“Gateway 可达、代码闭环已接通，但 broker order 证据链仍待补齐”的 backend。下一次有效行情下的 paper smoke 需要补齐 submit / query / reconcile / cancel 或 fill 证据。

完成一次有效行情 smoke 后，先用成熟度报告确认状态：

```bash
qexec evidence-maturity
```

再用审计 `run_id` 生成复查包：

```bash
qexec evidence-pack <audit-run-id>
qexec evidence-pack <audit-run-id> --operator-note "IBKR paper order evidence reviewed"
```

如果 evidence bundle 里缺少 smoke JSON、audit JSONL 或 state snapshot，这次运行只能算部分证据，不能把 `ibkr-paper` 提升为完整 broker-order 成熟路径。
