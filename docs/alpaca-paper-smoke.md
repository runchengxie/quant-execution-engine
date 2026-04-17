# Alpaca Paper Smoke（最小操作员路径）

本文档给出 `alpaca-paper` 的最小可复查 smoke 路径，目标是快速确认：

- 凭证加载可用；
- `config / preflight / account / quote / rebalance --execute / orders / reconcile` 操作员链路可达；
- 可以留下一份本地 evidence JSON 供后续复查。

> 定位说明：`alpaca-paper` 当前作为便宜、稳定、可重复的 paper 回归基线使用，不覆盖实盘路径。

## 1) 准备依赖

```bash
uv sync --group dev --extra cli --extra alpaca
```

## 2) 准备环境变量

至少提供一组 Alpaca paper 凭证：

- `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

建议先在当前 shell 临时导出，避免把凭证固化到仓库文件。

## 3) 先跑只读预检查（推荐）

```bash
qexec config --broker alpaca-paper
qexec preflight --broker alpaca-paper
qexec account --broker alpaca-paper --format json
qexec quote AAPL --broker alpaca-paper
```

如果这里失败，先修凭证、网络或 market-data 权限，不要直接进入 `--execute`。

## 4) 最小执行路径

准备一个 schema-v2 的 `targets.json`（例如 `outputs/targets/alpaca-paper-smoke.json`），然后：

```bash
qexec rebalance outputs/targets/alpaca-paper-smoke.json --broker alpaca-paper
qexec rebalance outputs/targets/alpaca-paper-smoke.json --broker alpaca-paper --execute
qexec orders --broker alpaca-paper --status open
qexec reconcile --broker alpaca-paper
qexec exceptions --broker alpaca-paper --status failure
```

如果只想验证操作员固定流程，也可以直接使用 harness：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/alpaca-paper-smoke.json
```

## 5) 建议留存的证据

至少保留：

- `outputs/orders/*.jsonl`（审计日志）
- `outputs/state/*.json`（本地执行状态）
- `outputs/evidence/alpaca-paper-smoke.json`（如果使用了 `--evidence-output`）

拿到 `audit_run_id` 后，建议再打一个复查包：

```bash
qexec evidence-pack <audit-run-id>
qexec evidence-pack <audit-run-id> --operator-note "alpaca paper smoke reviewed"
```

默认输出目录：`outputs/evidence-bundles/<audit-run-id>`。

## 6) 常见失败点

- 凭证变量缺失或 key/secret 不匹配；
- paper 账户或行情权限异常；
- 市场状态导致报价/下单行为与预期不同；
- 本地已有未处理 tracked order，需要先 `qexec cancel-all --broker alpaca-paper` 或先 `qexec reconcile` 再重试。

