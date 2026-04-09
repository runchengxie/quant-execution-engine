# Quant Execution Engine

面向 LongPort 的轻量 execution-only 仓库。

这个 repo 当前保留的能力：

- 查看有效 broker 配置
- 查询账户资金与持仓
- 拉取实时行情
- 基于 canonical `targets.json` 生成调仓计划与 diff 预览
- 写出调仓审计日志到 `outputs/orders/*.jsonl`

research、AI、回测、数据导入相关内容已经从这个仓库移除。

当前实现限制：

- `qexec rebalance ... --execute` 会进入 live-mode 路径并写 live-mode 审计日志，但 broker submit 分支目前仍返回模拟 `order_id`，还没有真正调用 LongPort 下单接口。
- `rebalance --account` 目前只作为兼容参数记录到日志里，还不会切换实际 broker 账户。

## 快速开始

安装依赖：

```bash
uv sync --group dev --extra cli
```

运行 CLI：

```bash
qexec --help
qexec config
qexec account --format json
qexec quote AAPL 700.HK
qexec rebalance outputs/targets/2026-04-09.json
qexec rebalance outputs/targets/2026-04-09.json --execute
```

也可以直接用模块入口：

```bash
PYTHONPATH=src python -m quant_execution_engine --help
```

`stockq` 仍保留为兼容别名，但后续文档统一使用 `qexec`。

## 配置

需要设置 LongPort 环境变量：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`

可选环境变量、本地 YAML 配置和 FX 折算见：

- [docs/configuration.md](docs/configuration.md)

`config/template.yaml` 提供了 execution-only 的最小本地配置模板，`.env.example` 提供了最小环境变量示例。

## 测试

默认测试只跑快速单元测试：

```bash
uv run pytest
```

按需运行其他测试层级：

```bash
uv run pytest -m e2e
uv run pytest -m integration
```

如果你想看覆盖率，可以显式开启，而不是让默认测试强制失败：

```bash
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

## 文档

- [docs/architecture.md](docs/architecture.md)
- [docs/cli.md](docs/cli.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/testing.md](docs/testing.md)
- [docs/targets.md](docs/targets.md)

## 输入约定

执行引擎只接受 canonical schema-v2 `targets.json`。

- 不再接受 Excel
- 不再接受 legacy ticker-list 作为 live execution 输入

最小示例：

```json
{
  "schema_version": 2,
  "asof": "2026-04-09",
  "source": "research-core",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_weight": 0.5
    },
    {
      "symbol": "700",
      "market": "HK",
      "target_weight": 0.5
    }
  ]
}
```
