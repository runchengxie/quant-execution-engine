# Testing

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
  真实 LongPort API 相关测试，需要本地凭证和网络。
- `tests/e2e/`
  通过 subprocess 跑 CLI 的端到端 smoke 测试。

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

- 覆盖率现在是显式选择的附加视角，不再绑在默认 `pytest` 入口上。
- 这个仓库更适合追求“关键路径有行为测试”，而不是强推一个固定的最低百分比。
- 如果后续要恢复硬性门槛，至少应该基于更高价值的行为测试覆盖，而不是依赖静态文件内容断言来堆数字。

## 运行前提

- `tests/integration/` 依赖 `LONGPORT_APP_KEY`、`LONGPORT_APP_SECRET`、`LONGPORT_ACCESS_TOKEN`。
- `tests/e2e/` 大多不需要真实凭证，但其中的 live quote 用例在没凭证时会自动跳过。
