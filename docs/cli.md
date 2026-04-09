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

显示当前 LongPort 有效配置摘要。

```bash
qexec config
```

### `account`

查看账户概览。

```bash
qexec account
qexec account --format json
qexec account --funds
qexec account --positions
```

### `quote`

查询实时行情。

```bash
qexec quote AAPL 700.HK
```

### `rebalance`

从 canonical `targets.json` 生成预览或执行调仓。

```bash
qexec rebalance outputs/targets/2026-04-09.json
qexec rebalance outputs/targets/2026-04-09.json --execute
qexec rebalance outputs/targets/2026-04-09.json --target-gross-exposure 0.9
```

## 行为约定

- `rebalance` 先做本地文件和格式校验，再触发 LongPort 相关逻辑。
- 非 `.json` 输入会被直接拒绝。
- schema-v1 / legacy ticker-list 不能作为 live execution 输入。
- `--execute` 缺省关闭；默认是 dry-run。
