# quant-execution-engine

`quant-execution-engine` 是量化研发工作区的交易执行层。它读取标准 `targets.json`，完成执行前检查、调仓预演、券商下单、订单追踪、异常恢复和审计。

```text
targets.json → preflight → dry-run → execute → reconcile → evidence
```

策略研究、历史回测、信号生成和原始数据采集由其他仓库维护。

## 当前能力

- 检查券商配置、账户、行情、风控和紧急停单状态
- 把目标持仓转换为调仓计划
- 提交、查询、撤销和对账
- 追踪订单状态并处理异常恢复
- 保存审计日志、执行状态和证据包

券商支持范围、成熟度和限制见 [docs/current-capabilities.md](docs/current-capabilities.md)。

## 安装

```bash
uv sync --group dev --extra cli
```

券商依赖按需安装：

```bash
uv sync --group dev --extra cli --extra longport
uv sync --group dev --extra cli --extra alpaca
uv sync --group dev --extra cli --extra ibkr
```

## 最小流程

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

当前没有默认券商。实盘需要人工监督和显式保护开关。

## 输入和输出

输入格式见 [docs/targets.md](docs/targets.md)。

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

扩展测试和发布诊断：

```bash
make test-all
make test-integration
make test-e2e
make basedpyright
```

详细范围见 [docs/testing.md](docs/testing.md)。

## 文档入口

- [文档首页](docs/README.md)
- [当前能力](docs/current-capabilities.md)
- [命令行](docs/cli.md)
- [配置和凭证](docs/configuration.md)
- [目标文件格式](docs/targets.md)
- [测试](docs/testing.md)
- [架构](docs/architecture.md)
- [长桥实盘演练](docs/longport-real-smoke.md)
