# quant-execution-engine

`quant-execution-engine` 是量化研发工作区的交易执行层。它读取标准 `targets.json`，完成执行前检查、调仓预演、券商下单、订单追踪、异常恢复和审计证据留存。

本仓库负责最后一段执行链路：

```text
targets.json
  ↓
preflight
  ↓
rebalance dry-run
  ↓
execute
  ↓
reconcile
  ↓
evidence
```

策略研究、历史回测、信号生成和原始数据采集由其他仓库维护。

## 当前能力

核心能力包括：

- 检查券商配置、账户、行情、风控和紧急停单状态
- 把目标持仓转换为调仓计划
- 在执行前展示差异和订单意图
- 提交、查询、撤销和对账
- 追踪本地订单状态
- 处理重试、改价、部分成交和异常恢复
- 保存审计日志、执行状态和证据包

券商支持范围、成熟度和已知限制见 [docs/current-capabilities.md](docs/current-capabilities.md)。

## 安装

安装开发和命令行依赖：

```bash
uv sync --group dev --extra cli
```

按需安装券商依赖：

```bash
uv sync --group dev --extra cli --extra longport
uv sync --group dev --extra cli --extra alpaca
uv sync --group dev --extra cli --extra ibkr
```

## 最小流程

查看配置并执行只读检查：

```bash
qexec config --broker longport-paper
qexec preflight --broker longport-paper
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper
```

确认调仓计划后，模拟盘可以显式执行：

```bash
qexec rebalance outputs/targets/2026-04-09.json \
  --broker longport-paper \
  --execute
qexec orders --broker longport-paper --status open
qexec reconcile --broker longport-paper
```

当前没有默认券商。请在 `config/config.yaml` 中配置 `broker.backend`，或在命令中传入 `--broker`。

实盘需要人工监督和显式保护开关。长桥实盘操作前先读 [docs/longport-real-smoke.md](docs/longport-real-smoke.md)。

## 输入和输出

输入格式见 [docs/targets.md](docs/targets.md)。

常见本地产物：

```text
outputs/orders/*.jsonl
outputs/state/*.json
outputs/evidence/*.json
outputs/evidence-bundles/*
```

这些目录用于审计和复查，默认不进入 Git。

## 测试和质量检查

```bash
make test
make lint
make format
make typecheck
make quality
```

完整测试集、集成测试和端到端测试需要显式运行：

```bash
make test-all
make test-integration
make test-e2e
```

BasedPyright 用于发布前诊断：

```bash
make basedpyright
```

详细范围见 [docs/testing.md](docs/testing.md)。

## 工作区边界

| 仓库 | 职责 |
| --- | --- |
| `market-data-platform` | 数据资产 |
| `alpha-research` | 特征、模型和信号 |
| `portfolio-backtester` | 组合构造和回测 |
| `strategy-pipeline` | 编排和 `targets.json` 导出 |
| `quant-execution-engine` | 风控、执行、对账和审计 |

## 文档入口

- [文档首页](docs/README.md)
- [当前能力](docs/current-capabilities.md)
- [命令行](docs/cli.md)
- [配置和凭证](docs/configuration.md)
- [目标文件格式](docs/targets.md)
- [研究交接治理](docs/research-handoff-governance.md)
- [测试](docs/testing.md)
- [架构](docs/architecture.md)
- [执行基础](docs/execution-foundation.md)
- [长桥实盘演练](docs/longport-real-smoke.md)
