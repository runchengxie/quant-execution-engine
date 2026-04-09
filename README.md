# Quant Execution Engine

面向 LongPort 的轻量交易执行仓库。

这个 repo 只保留 execution 侧能力：

- 查看有效 broker 配置
- 查询账户资金与持仓
- 拉取实时行情
- 基于 canonical `targets.json` 生成调仓计划并执行

research、AI、回测、数据导入相关内容已经从这个仓库移除。

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

可选环境变量和本地 YAML 配置见：

- [docs/configuration.md](docs/configuration.md)

## 文档

- [docs/architecture.md](docs/architecture.md)
- [docs/cli.md](docs/cli.md)
- [docs/configuration.md](docs/configuration.md)
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
