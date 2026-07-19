# 测试和本地门禁

本页说明 `quant-execution-engine` 的测试分层、质量范围和推送前检查。券商支持范围与证据成熟度见 [current-capabilities.md](current-capabilities.md)。

## 常用命令

```bash
make test
make test-all
make test-integration
make test-e2e
make lint
make format
make typecheck
make basedpyright
make maintainability
make quality
```

| 命令 | 实际范围 |
| --- | --- |
| `make test` | 默认快速测试 |
| `make test-all` | 清除默认标记过滤，运行完整测试集 |
| `make test-integration` | 集成测试 |
| `make test-e2e` | 端到端测试 |
| `make lint` | 对 `src/`、`tests/`、`scripts/` 和 `project_tools/` 运行 Ruff |
| `make format` | 检查上述目录的 Ruff 格式 |
| `make typecheck` | 对 `pyproject.toml` 中的 `ty` 范围做基础类型检查 |
| `make basedpyright` | 对 `src/quant_execution_engine/` 做 BasedPyright 发布诊断 |
| `make maintainability` | 检查全仓 Python 维护性预算 |
| `make quality` | 依次运行 lint、format、typecheck、maintainability 和默认测试 |

## Pytest 分层

`pyproject.toml` 的默认过滤会跳过 `integration`、`e2e` 和 `slow`。`make test` 适合日常回归。

| 标记 | 用途 |
| --- | --- |
| `unit` | 快速、隔离的行为测试 |
| `integration` | 需要外部 API、本地网关或数据库 |
| `e2e` | 通过子进程验证完整命令链路 |
| `slow` | 运行时间较长 |
| `requires_api` | 需要外部 API |
| `requires_db` | 需要数据库 |

目录职责：

- `tests/unit/` 覆盖命令路由、订单生命周期、预检、风控、本地状态和渲染
- `tests/integration/` 覆盖券商适配器、对账、紧急停单和外部环境
- `tests/e2e/` 通过子进程验证命令行和操作员工装

真实券商测试需要显式环境变量和人工监督。缺少凭证、网络或本地网关时，相关用例应跳过或快速失败。

按需生成覆盖率报告：

```bash
uv run pytest \
  --cov=src/quant_execution_engine \
  --cov-report=term-missing \
  -m 'not integration and not e2e and not slow'
```

## 维护性预算

`scripts/dev/maintainability_metrics.py` 统计 `src/`、`tests/`、`scripts/` 和 `project_tools/`。`--ratchet` 在任一指标超过预算时失败。

当前预算：

| 指标 | 上限 |
| --- | ---: |
| 超过 100 字符的代码行 | 0 |
| 超过 100 行的函数 | 21 |
| 超过 250 行的函数 | 2 |
| 超过 500 行的函数 | 0 |
| 文件级 `C901` 豁免 | 1 |
| 超过 800 行的文件 | 7 |
| 超过 1200 行的文件 | 3 |
| 超过 1000 行的测试文件 | 3 |

预算只随结构改善收紧。新增代码应避免扩大现有债务。

## 类型检查

`ty` 是日常基础门禁，其文件范围在 `[tool.ty.src]` 中维护。BasedPyright 的 `basic` 模式覆盖整个产品包，用于发布前诊断。当前工具链不使用 `mypy`。

## 推送前检查

`research-workspace` 托管检出使用 superproject 的共享 `pre-push`。钩子按 `scripts/submodule_checks.json` 派发检查，同时校验分支、引用和 gitlink 状态。

单独克隆本仓库时不会自动获得共享钩子。推送前至少运行：

```bash
make quality
```

涉及类型边界、券商适配器或发布准备时，再运行：

```bash
make basedpyright
make test-all
```

## 券商演练文档

- [Alpaca 模拟盘演练](alpaca-paper-smoke.md)
- [盈透模拟盘演练](ibkr-paper-smoke.md)
- [长桥模拟盘失败场景](longport-paper-failure-smoke.md)
- [长桥实盘谨慎演练](longport-real-smoke.md)

默认测试只证明离线行为回归通过。模拟盘和实盘成熟度还需结合受监督演练、审计日志和本地证据判断。

## 自动化状态

当前仓库没有启用 GitHub Actions 测试工作流。质量检查在本地 Makefile 和 superproject 共享钩子中完成。
