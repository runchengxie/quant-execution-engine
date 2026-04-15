# 测试

## 默认入口

默认测试入口是：

```bash
uv run pytest
```

它只跑快速测试，默认排除这些 marker：

- `integration`
- `e2e`
- `slow`

## 测试分层

- `tests/unit/`
  快速、隔离的行为测试。这里覆盖 CLI 路由、lifecycle、partial-fill 恢复、preflight、本地 state 维护和 renderers。
- `tests/integration/`
  覆盖 adapter / lifecycle 的跨模块行为，例如 reconcile、kill switch、状态恢复，以及带凭证时的 LongPort quote 级别验证。
- `tests/e2e/`
  通过 subprocess 跑 CLI 和 smoke harness 的端到端 smoke 测试。

## 常用命令

只跑单元测试：

```bash
uv run pytest
```

只跑 e2e：

```bash
uv run pytest -m e2e
```

只跑 integration：

```bash
uv run pytest -m integration
```

按需查看覆盖率：

```bash
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

## 当前测试证明了什么

- 默认 `pytest` 能证明快速行为测试通过。
- lifecycle 相关单测覆盖了 tracked order 的 retry、reprice、reconcile、partial-fill operator action、pending-cancel、late-fill 恢复，以及 state doctor/prune/repair。
- CLI 单测覆盖了新旧命令的分发和 live guard 行为。
- e2e 当前证明了 CLI / harness 的 subprocess smoke 行为，包括 signal/target harness 输出、operator harness 的非 paper 拒绝路径。
- `smoke_operator_harness.py` 已有单测覆盖固定 workflow、preflight-only 路径、下游 operator step 失败，以及 evidence JSON 输出。
- `longport-paper` 已经是正式 broker backend；提供 `LONGPORT_ACCESS_TOKEN_TEST` 后，可以走 paper preflight / rebalance 路径。
- `longport-paper` 当前已经通过 operator-supervised paper smoke 跑通过 `submit / query / reconcile / cancel` 最小闭环；这是一条可复现的 paper 证据链，但不是默认自动化测试的一部分。
- 截至 2026-04-15，LongPort real 已经通过 operator-supervised read-only 验证跑通 `config / preflight / account / quote`，并确认用户私有 live 配置路由和 live guard 可工作。
- LongPort live quote 相关测试现在会把典型的网络 / 区域 / 凭证异常视为 skip，而不是误报失败。

## 当前测试还没有证明什么

- 这些测试不能单独证明 LongPort real broker 的完整 `submit / query / cancel / reconcile` 已经被自动化端到端跑实。
- 当前最便宜、最稳定的回归基线仍然是 Alpaca paper；`longport-paper` 则是已经有 broker-backed 证据链的 LongPort paper 路径。
- real broker 成熟度判断仍要看 operator-supervised smoke、审计日志和可复现 evidence，而不是只看默认测试绿了。

## 运行前提

- `tests/integration/` 的 LongPort live quote 用例依赖 `LONGPORT_APP_KEY`、`LONGPORT_APP_SECRET`、`LONGPORT_ACCESS_TOKEN`。
- `tests/e2e/` 大多不需要真实凭证；凭证缺失或网络 / 区域不可达时，live quote 相关用例会自动跳过。
- Alpaca 相关路径默认不会在测试里真实联网；需要真实 paper 验证时再单独配 `ALPACA_*` 环境变量并显式跑场景。

## Operator Smoke

如果你想重复验证 paper account 的执行主路径和 operator 命令，可以直接跑：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

如果你只想先确认依赖、凭证、账户和行情都正常，不想写 targets 或发单，可以先跑：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
```

如果你希望把一次 smoke 运行沉淀成可复查的证据，可以加：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/operator-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

如果 workflow 中途某一步失败，`--evidence-output` 现在也会保留 partial evidence，包括：

- 已完成步骤
- 失败步骤名
- 失败步骤的 exit code / stderr
- 稳定的 `failure_category`
- 保守的 `next_step_hint`
- `skipped_steps`，说明哪些步骤没有继续执行，以及为什么被跳过

默认 workflow 会串起这些步骤：

1. `config`
2. `account`
3. `quote`
4. 写出一个最小 `targets.json`
5. `rebalance --execute`
6. `orders`
7. `order`，如果本地 state 里找到了最新 tracked order
8. `reconcile`
9. `exceptions`
10. 可选 `cancel-all`

如果你想在 paper 环境末尾顺手清掉仍然 open 的 tracked orders，可以加：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --cleanup-open-orders
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders
```

这个工装默认拒绝 non-paper broker；如果你明确知道自己要这么做，需要额外传 `--allow-non-paper`。

如果你准备开始做 LongPort real 的最小实盘验证，先看 [docs/longport-real-smoke.md](longport-real-smoke.md)。
