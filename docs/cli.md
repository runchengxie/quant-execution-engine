# CLI

## 命令入口

推荐入口：

```bash
qexec
```

兼容入口：

```bash
stockq
```

开发环境也可以直接执行：

```bash
PYTHONPATH=src python -m quant_execution_engine
```

## 子命令

### `config`

显示当前 broker backend、risk gate、kill switch 和相关凭证摘要。

```bash
qexec config
qexec config --broker alpaca-paper
```

### `account`

查看账户概览。

```bash
qexec account
qexec account --format json
qexec account --funds
qexec account --positions
qexec account --broker alpaca-paper
qexec account --account main
```

### `quote`

查询实时行情。

```bash
qexec quote AAPL 700.HK
qexec quote AAPL --broker alpaca-paper
```

### `rebalance`

从 canonical `targets.json` 生成预览或进入 live-mode 调仓路径。

```bash
qexec rebalance outputs/targets/2026-04-09.json
qexec rebalance outputs/targets/2026-04-09.json --account main
QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --execute
qexec rebalance outputs/targets/2026-04-09.json --broker alpaca-paper --execute
qexec rebalance outputs/targets/2026-04-09.json --target-gross-exposure 0.9
```

## 行为约定

- `rebalance` 先做本地文件和格式校验，再触发 broker adapter 相关逻辑。
- 非 `.json` 输入会被直接拒绝。
- schema-v1 / legacy ticker-list 不能作为 live execution 输入。
- `--execute` 缺省关闭；默认是 dry-run。
- real broker 的 `--execute` 额外要求 `QEXEC_ENABLE_LIVE=1`。
- `--broker` 默认读取本地配置里的 backend，没有配置时默认 `longport`。
- `--account` 会先走 adapter account/profile 校验；不支持的 label 会 fail fast。
- `--execute` 会进入 broker-backed submit/query/reconcile 路径，并写出 richer audit/state 输出。
- real broker 的 `--execute` 会扫描 repo 根目录 `.env*` / `.envrc*`；如果发现 LongPort live 凭证，CLI 会直接拒绝执行。
- live / paper 下单前会经过 execution risk gate；如果 spread、参与率、impact 或 kill switch 拦截，CLI 输出里会看到 `BLOCKED` 和具体原因。
- `rebalance` 每次运行都会写审计日志到 `outputs/orders/*.jsonl`。
- 活跃执行状态会持久化到 `outputs/state/*.json`，用于幂等、防重放和重启恢复。

## 测试运行

repo 内置两个外置工装：

```bash
PYTHONPATH=src python project_tools/smoke_signal_harness.py --output outputs/targets/smoke-signal.json
PYTHONPATH=src python project_tools/smoke_target_harness.py --scenario rebalance --print-json
```

它们会生成 canonical `targets.json`，必要时还能直接调用 `qexec rebalance`。这些工装用于验证执行行为。
