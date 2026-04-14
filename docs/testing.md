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
  快速、隔离的行为测试，应该是日常改动的默认入口。
- `tests/integration/`
  覆盖 adapter/lifecycle 的跨模块行为，例如 reconcile、kill switch、重启恢复；可以用 fake adapter，也可以扩展到真实 broker backend。
- `tests/e2e/`
  通过 subprocess 跑 CLI 和 smoke harness 的端到端 smoke 测试。

当前目录分层本身不算过度；更需要避免的是低价值的静态字符串断言和重复的 CLI smoke 套测。

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

## 覆盖率策略

- 覆盖率现在是显式选择的附加视角。
- 这个仓库采用关键路径有行为测试的思路。

## 运行前提

- `tests/integration/` 依赖 `LONGPORT_APP_KEY`、`LONGPORT_APP_SECRET`、`LONGPORT_ACCESS_TOKEN`。
- `tests/e2e/` 大多不需要真实凭证，但其中的 live quote 用例在没凭证时会自动跳过。
- Alpaca 相关路径默认不会在测试里真实联网；需要真实 paper 验证时再单独配 `ALPACA_*` 环境变量并显式跑场景。

## Alpaca Paper Smoke 回归

如果你想重复验证 paper account 的执行主路径和 operator 命令，可以直接跑外置工装：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute
```

如果你只想先确认依赖、凭证、账户和行情都正常，不想写 targets 或发单，可以先跑：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
```

默认 workflow 会串起这些步骤：

1. `config`
2. `account`
3. `quote`
4. 写出一个最小 `targets.json`
5. `rebalance --execute`
6. `orders`
7. `order`（如果本地 state 里找到了最新 tracked order）
8. `reconcile`
9. `exceptions`

如果你想在 paper 环境末尾顺手清掉仍然 open 的 tracked orders，可以加：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --cleanup-open-orders
```

这个工装默认拒绝 non-paper broker；如果你明确知道自己要这么做，需要额外传 `--allow-non-paper`。
