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
  快速、隔离的行为测试。这里覆盖 CLI 路由、生命周期、部分成交恢复、`preflight`、本地状态维护和渲染器。
- `tests/integration/`
  覆盖适配器 / 生命周期的跨模块行为，例如 `reconcile`、紧急停单、状态恢复，以及在提供凭证或本地 runtime 时的 LongPort / IBKR broker-backed 验证。
- `tests/e2e/`
  通过子进程运行 CLI 和冒烟工装的端到端冒烟测试。

## 常用命令

只跑单元测试：

```bash
uv run pytest
```

只跑 `e2e`：

```bash
uv run pytest -m e2e
```

只跑 `integration`：

```bash
uv run pytest -m integration
```

按需查看覆盖率：

```bash
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

## 当前测试证明了什么

- 默认 `pytest` 能证明快速行为测试通过。
- 生命周期相关单测覆盖了已跟踪订单的 `retry`、`reprice`、`reconcile`、部分成交操作员处置、`pending-cancel`、迟到成交恢复，以及 `state doctor/prune/repair`。
- CLI 单测覆盖了新旧命令的分发和实盘保护行为。
- `e2e` 当前证明了 CLI / 工装的子进程冒烟行为，包括信号 / 目标持仓工装输出、操作员工装的非模拟盘拒绝路径。
- `smoke_operator_harness.py` 已有单测覆盖固定流程、`preflight-only` 路径、下游操作员步骤失败，以及证据 JSON 输出。
- `longport-paper` 已经是正式券商后端；提供 `LONGPORT_ACCESS_TOKEN_TEST` 后，可以走模拟盘 `preflight / rebalance` 路径。
- `ibkr-paper` 已经有单测覆盖 backend 注册、config surfacing、market/account 校验、order/fill 归一化，以及 smoke harness 的 IBKR 环境快照路径。
- `longport-paper` 当前已经通过人工监督的模拟盘冒烟，跑通 `submit / query / reconcile / cancel` 最小闭环；这是一条可复现的模拟盘证据链，默认自动化测试不包含这一段。
- 截至 2026-04-16，`ibkr-paper` 已有一次人工监督 no-order evidence：WSL 内 CLI 可连 Windows IB Gateway 的 `127.0.0.1:4002`，并跑通 `config / account / quote / rebalance / reconcile / exceptions / cancel-all`，但 AAPL 行情因 IBKR competing live session 返回 0，`audit_order_count=0`。
- 截至 2026-04-15，LongPort 实盘已经通过人工监督只读验证跑通 `config / preflight / account / quote`，并确认用户私有实盘配置路由和实盘保护可工作。
- LongPort 实盘行情相关测试现在会把典型的网络 / 区域 / 凭证异常记为跳过。

## 当前测试还没有证明什么

- 这些测试不能单独证明 LongPort 实盘完整 `submit / query / cancel / reconcile` 已经被自动化端到端跑实。
- 当前最便宜、最稳定的回归基线仍然是 Alpaca 模拟盘；`longport-paper` 则是已经有券商侧证据链的 LongPort 模拟盘路径。
- `ibkr-paper` 当前仍缺有效行情下的 broker order evidence；现阶段更适合作为本地 Gateway 驱动的增量 backend，而不是主回归基线。
- 实盘券商成熟度判断以人工监督冒烟、审计日志和可复查证据为准。

## 运行前提

- `tests/integration/` 的 LongPort 实盘行情用例依赖 `LONGPORT_APP_KEY`、`LONGPORT_APP_SECRET`、`LONGPORT_ACCESS_TOKEN`。
- `tests/integration/test_ibkr_paper_integration.py` 依赖本地已启动并登录的 IB Gateway，以及显式 opt-in 的 `IBKR_ENABLE_INTEGRATION=1`；涉及提交/撤单的用例还要求 `IBKR_ENABLE_MUTATION_TESTS=1`，fill 路径要求 `IBKR_ENABLE_FILL_TESTS=1`。
- `tests/e2e/` 大多不需要真实凭证；凭证缺失或网络 / 区域不可达时，实盘行情相关用例会自动跳过。
- Alpaca 相关路径默认不会在测试里真实联网；需要真实模拟盘验证时，再单独配 `ALPACA_*` 环境变量并显式跑场景。

## Operator 冒烟

如果你想重复验证模拟盘账户的执行主路径和操作员命令，可以直接跑：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --execute --evidence-output outputs/evidence/ibkr-paper-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

如果你只想先确认依赖、凭证、账户和行情都正常，不想写 `targets` 或发单，可以先跑：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
```

如果你希望把一次冒烟沉淀成可复查证据，可以加：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/operator-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --execute --evidence-output outputs/evidence/ibkr-paper-smoke.json --operator-note "operator supervised paper smoke"
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport --allow-non-paper --execute --evidence-output outputs/evidence/longport-real-smoke.json --operator-note "operator supervised" --operator-note "cancel not covered"
```

如果流程中途某一步失败，`--evidence-output` 现在也会保留部分证据，包括：

- 已完成步骤
- 失败步骤名
- 失败步骤的退出码 / stderr
- 稳定的 `failure_category`
- 保守的 `next_step_hint`
- `skipped_steps`，说明哪些步骤没有继续执行，以及为什么被跳过

如果流程本身跑完了，但当前已跟踪结果是本地 `BLOCKED` 或其他仍需操作员判断的状态，证据还会额外保留：

- `operator_outcome_status`
- `operator_outcome_source`
- `operator_outcome_message`
- `operator_outcome_category`
- `operator_next_step_hint`
- `audit_log_path` / `audit_run_id`
- `operator_notes`

默认流程会串起这些步骤：

1. `config`
2. `account`
3. `quote`
4. 写出一个最小 `targets.json`
5. `rebalance --execute`
6. `orders`
7. `order`，如果本地状态里找到了最新已跟踪订单
8. `reconcile`
9. `exceptions`
10. 可选 `cancel-all`

如果你想在模拟盘环境末尾顺手清掉仍然 open 的已跟踪订单，可以加：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --cleanup-open-orders
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders
```

这个工装默认拒绝非模拟盘券商；如果你明确知道自己要这么做，需要额外传 `--allow-non-paper`。

如果你准备开始做 IBKR 模拟盘的最小验证，先看 [docs/ibkr-paper-smoke.md](ibkr-paper-smoke.md)。
如果你想系统化重复 `longport-paper` 的操作员失败场景冒烟，可先看 [docs/longport-paper-failure-smoke.md](longport-paper-failure-smoke.md)。

如果你准备开始做 LongPort 实盘的最小验证，先看 [docs/longport-real-smoke.md](longport-real-smoke.md)。
