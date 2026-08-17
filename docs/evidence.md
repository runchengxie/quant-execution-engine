# 离线证据链

本页说明如何用无网络的 `local-dry-run` 和 `mock-sim` 后端生成可复现的执行证据。能力边界见 [current-capabilities.md](current-capabilities.md)。

## 用途

这两条离线链路用于在隔离运行目录里验证执行主流程，并把审计日志、执行状态和证据 JSON 留存到同一目录，便于复查和恢复。

- `local-dry-run` 覆盖目标文件解析、预检、行情、账户和调仓预演。它不提供提交、撤单、订单查询或对账。
- `mock-sim` 覆盖提交、成交、查询、撤单和对账，并把模拟券商侧状态持久化到运行目录。

`mock-sim` 的证据只说明离线模拟行为，不传递到任何真实券商后端。

## 运行

```bash
PYTHONPATH=src uv run python project_tools/evidence_offline_chain.py \
  --broker local-dry-run --run-dir outputs/evidence-offline/local-dry

PYTHONPATH=src uv run python project_tools/evidence_offline_chain.py \
  --broker mock-sim --execute --restart-check --run-dir outputs/evidence-offline/mock
```

`--run-dir` 指定隔离目录。未指定时默认写入 `outputs/evidence-offline/<时间戳>`。

`mock-sim` 的 `--execute` 会执行模拟提交与成交链路，`--restart-check` 会模拟一次重启并从同一状态目录恢复，报告持仓和追踪订单数量是否一致。

## 运行目录结构

```text
<run-dir>/
  targets.json                调仓输入
  orders/*.jsonl              调仓审计日志
  state/*.json                本地执行状态
  mock-sim/*.json             模拟券商侧订单簿和持仓（mock-sim）
  evidence/<broker>-offline-chain.json  证据摘要
```

`QEXEC_OUTPUTS_DIR` 把审计日志、执行状态和证据 JSON 重定向到运行目录，使整条链路自包含。

## 验证项

本地默认测试覆盖了 `mock-sim` 的提交、成交、撤单、查询、对账和持久化行为。离线证据链的端到端测试位于 `tests/e2e/test_evidence_offline_chain.py`，用 `-m e2e` 运行：

```bash
uv run pytest tests/e2e/test_evidence_offline_chain.py -m e2e -o addopts=''
```

真实券商能力仍以受监督演练和对应券商文档为准。
