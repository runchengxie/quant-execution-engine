# 测试和质量检查

本页说明 `quant-execution-engine` 的测试分层和本地命令。券商支持范围与证据成熟度见 [current-capabilities.md](current-capabilities.md)。

## 默认测试

```bash
uv run pytest
```

`pyproject.toml` 默认排除以下标记：

- `integration`
- `e2e`
- `slow`

默认命令适合快速行为回归。

## Pytest 标记

| 标记 | 用途 |
| --- | --- |
| `unit` | 快速、隔离的行为测试 |
| `integration` | 需要外部 API、本地网关或数据库 |
| `e2e` | 通过子进程验证完整命令链路 |
| `slow` | 运行时间较长 |
| `requires_api` | 需要外部 API |
| `requires_db` | 需要数据库 |

## Makefile 入口

```bash
make test
make test-all
make test-integration
make test-e2e
make lint
make format
make typecheck
make basedpyright
make quality
```

| 命令 | 实际范围 |
| --- | --- |
| `make test` | 默认快速测试 |
| `make test-all` | 清除默认标记过滤，运行完整测试集 |
| `make test-integration` | 集成测试 |
| `make test-e2e` | 端到端测试 |
| `make lint` | Ruff 代码检查 |
| `make format` | Ruff 格式检查 |
| `make typecheck` | `ty` 配置范围 |
| `make basedpyright` | BasedPyright 发布诊断 |
| `make quality` | lint、format、typecheck 和默认测试 |

按需生成覆盖率报告：

```bash
uv run pytest \
  --cov=src/quant_execution_engine \
  --cov-report=term-missing \
  -m 'not integration and not e2e and not slow'
```

## 测试分层

- `tests/unit/` 覆盖命令路由、订单生命周期、预检、风控、本地状态和渲染。
- `tests/integration/` 覆盖券商适配器、对账、紧急停单和外部环境。
- `tests/e2e/` 通过子进程验证命令行和操作员脚手架。

真实券商测试需要显式环境变量和人工监督。缺少凭证、网络或本地网关时，相关用例应跳过或快速失败。

## 测试重点

修改以下领域时应补充定点测试：

- `targets.json` 解析和版本兼容
- 执行前检查和风险降级
- 调仓计划与订单意图
- 提交、查询、撤销和对账
- 重试、改价和部分成交恢复
- 本地状态修复和异常诊断
- 证据输出与敏感文件排除
- 券商配置来源和实盘保护

默认测试只证明离线行为回归通过。模拟盘和实盘成熟度仍需结合受监督演练、审计日志和本地证据判断。

## 类型检查

基础类型门禁是 `ty`。BasedPyright 用于发布前诊断。两者的覆盖范围由 `pyproject.toml` 维护。

当前工具链不使用 `mypy`。

## 自动化状态

当前仓库没有启用 GitHub Actions 测试 workflow。本地 Makefile、`pyproject.toml` 和受监督验证记录是当前事实来源。
