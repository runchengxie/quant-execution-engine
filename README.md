# Quant Execution Engine

量化执行引擎。

它读取标准 `targets.json` 目标持仓文件，完成执行前检查、调仓预演、券商下单、订单追踪、异常恢复和审计证据留存。本仓库不做策略研究、历史回测、AI 信号生成或原始行情数据导入。

## 这个项目做什么

日常可以把它理解成研究系统之后的执行层：

```text
targets.json -> preflight -> rebalance dry-run -> execute -> reconcile -> evidence
```

核心能力是：

- 检查券商配置、账户、行情、风控和紧急停单状态。
- 把 `targets.json` 转成调仓计划，并在执行前展示差异预览。
- 通过券商适配器提交、查询、撤单和对账。
- 维护本地订单状态，提供异常订单查询、重试、改价、部分成交处理等操作入口。
- 保存调仓审计日志、本地状态和可复查的 evidence bundle。

当前支持范围、成熟度和已知缺口以 [docs/current-capabilities.md](docs/current-capabilities.md) 为准。

## 快速开始

安装核心命令行依赖：

```bash
uv sync --group dev --extra cli
```

按需要追加券商依赖：

```bash
uv sync --group dev --extra cli --extra longport
uv sync --group dev --extra cli --extra alpaca
uv sync --group dev --extra cli --extra ibkr
```

查看入口：

```bash
qexec --help
qexec config --broker longport-paper
qexec preflight --broker longport-paper
```

当前不假设默认券商。请在 `config/config.yaml` 中配置 `broker.backend`，或在命令中显式传入 `--broker`。

## 最小执行流程

先做只读检查和预演：

```bash
qexec config --broker longport-paper
qexec preflight --broker longport-paper
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper
```

确认无误后，模拟盘可以加 `--execute`：

```bash
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute
qexec orders --broker longport-paper --status open
qexec reconcile --broker longport-paper
```

实盘执行需要额外的人工监督和显式保护开关。长桥实盘操作前先读 [docs/longport-real-smoke.md](docs/longport-real-smoke.md)。

## 输入和输出

输入只接受标准 `targets.json`。格式说明见 [docs/targets.md](docs/targets.md)。

常见输出：

```text
outputs/orders/*.jsonl
outputs/state/*.json
outputs/evidence/*.json
outputs/evidence-bundles/*
```

这些目录用于本地审计和复查，默认不进入 Git。

## 与另外两个仓库的边界

- `market-data-platform`：生产、检查和发布共享市场数据资产。
- `cross-sectional-trees`：只读消费平台资产，做研究、回测和目标持仓导出。
- `quant-execution-engine`：读取标准 `targets.json`，负责 dry-run、风控、执行和审计。

本仓库只负责最后一段执行链路。

## 文档导航

- 先看文档首页：[docs/README.md](docs/README.md)
- 当前能力和限制：[docs/current-capabilities.md](docs/current-capabilities.md)
- 命令行说明：[docs/cli.md](docs/cli.md)
- 配置和凭证：[docs/configuration.md](docs/configuration.md)
- `targets.json` 格式：[docs/targets.md](docs/targets.md)
- 研究到执行交接治理：[docs/research-handoff-governance.md](docs/research-handoff-governance.md)
- 测试入口：[docs/testing.md](docs/testing.md)
- 架构说明：[docs/architecture.md](docs/architecture.md)
- 长桥实盘谨慎演练：[docs/longport-real-smoke.md](docs/longport-real-smoke.md)
