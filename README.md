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

## 框架边界

当前框架层由通用 `BrokerAdapter` 协议和类型化执行领域对象组成。已注册的具体券商后端仍以 [当前能力](docs/current-capabilities.md) 为准。

当前 `main` 没有 vn.py 适配器、依赖或已注册后端。Qlib、LEAN、Backtrader 及其他研究或回测框架不在本仓库范围内。Gateway 框架集成需要独立设计、恢复语义和受监督证据，不能依据通用协议推断为现有能力。

## 安装

支持 Python 3.10 至 3.12。`pyproject.toml` 的版本约束为 `>=3.10,<3.13`。

安装命令行和离线预演所需的最小依赖：

```bash
uv sync --extra cli
```

开发环境还需安装测试和质量工具：

```bash
uv sync --group dev --extra cli
```

券商 SDK 按需安装：

```bash
uv sync --group dev --extra cli --extra longport
uv sync --group dev --extra cli --extra alpaca
uv sync --group dev --extra cli --extra ibkr
```

长桥命令需要 `longport` 额外依赖和对应环境的凭证。模拟盘与实盘使用不同令牌，实盘还需要 `QEXEC_ENABLE_LIVE=1`。配置位置和保护规则见 [docs/configuration.md](docs/configuration.md)。

## 最小流程

先用无网络的 `local-dry-run` 检查目标文件和调仓计划：

```bash
qexec config --broker local-dry-run
qexec preflight --broker local-dry-run
qexec rebalance examples/targets.local-dry-run.json --broker local-dry-run
```

准备好长桥模拟盘依赖和凭证后，可以运行：

```bash
qexec config --broker longport-paper
qexec preflight --broker longport-paper
qexec rebalance <targets.json> --broker longport-paper
```

确认调仓计划后，模拟盘可以显式执行：

```bash
qexec rebalance <targets.json> \
  --broker longport-paper \
  --execute
qexec orders --broker longport-paper --status open
qexec reconcile --broker longport-paper
```

当前没有默认券商。实盘操作需要人工监督和显式保护开关。

## 输入和输出

目标文件格式见 [docs/targets.md](docs/targets.md)。运行产物默认写入以下目录：

```text
outputs/orders/*.jsonl
outputs/state/*.json
outputs/evidence/*.json
outputs/evidence-bundles/*
```

这些目录用于审计和复查，默认不进入 Git。

## 本地质量检查

```bash
make quality
make test-all
```

`make quality` 覆盖全仓 Ruff 检查、格式检查、完整产品包的 `ty` 类型检查、维护性预算和默认测试。完整范围见 [docs/testing.md](docs/testing.md)。

在 `research-workspace` 托管检出中，共享 `pre-push` 会按工作区清单派发本地检查。单独克隆本仓库时，应在推送前手动运行 `make quality`。

## 文档入口

- [文档首页](docs/README.md)
- [当前能力](docs/current-capabilities.md)
- [命令行](docs/cli.md)
- [配置和凭证](docs/configuration.md)
- [目标文件格式](docs/targets.md)
- [测试和本地门禁](docs/testing.md)
- [架构](docs/architecture.md)
- [类型化执行领域](docs/typed-execution-domain.md)
- [订单生命周期](docs/execution-foundation.md)
- [长桥实盘演练](docs/longport-real-smoke.md)
