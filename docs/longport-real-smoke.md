# 长桥 LongPort 实盘冒烟测试

这份文档的目标：

- 为 `longport` real broker 提供一套最小实盘冒烟测试playbook
- 补 `submit / query / reconcile / cancel` 的证据链
- 不把 live secret 留在 repo 根目录 `.env*` / `.envrc*`

## 1. 什么时候值得开始

只有在下面这些前提满足时，才值得把 LongPort real token 加进来：

- `longport-paper` 已经跑通，readiness 和 operator workflow 没有明显未知数
- 你准备做一次最小、人工盯盘的 real smoke
- 你接受 live 路径要以极小仓位、明确证据留存和人工确认来推进

如果你还只是想继续打磨 execution 语义、CLI 行为或 paper failure mode，先不用急着加 real token。

## 2. live token 怎么放

不要把 real 凭证写进 repo 根目录这些文件：

- `.env`
- `.env.local`
- `.envrc`
- `.envrc.local`

当前 CLI 会把 repo 根目录里的 LongPort live 凭证视为危险配置，并在 real `--execute` 路径上拒绝继续。

推荐的做法只有两种：

1. 在当前 shell 临时 `export`
2. `source` 一个放在 repo 外面的私有文件

### 推荐方式 A：当前 shell 临时导出

```bash
export LONGPORT_APP_KEY="..."
export LONGPORT_APP_SECRET="..."
export LONGPORT_ACCESS_TOKEN="..."
export LONGPORT_REGION="cn"
export LONGPORT_ENABLE_OVERNIGHT="true"
export QEXEC_ENABLE_LIVE="1"
```

### 推荐方式 B：从 repo 外部私有文件导入

先在仓库外保存一个私有文件，例如 `~/.config/qexec/longport-live.env`：

```bash
export LONGPORT_APP_KEY="..."
export LONGPORT_APP_SECRET="..."
export LONGPORT_ACCESS_TOKEN="..."
export LONGPORT_REGION="cn"
export LONGPORT_ENABLE_OVERNIGHT="true"
export QEXEC_ENABLE_LIVE="1"
```

然后在当前 shell 里执行：

```bash
source ~/.config/qexec/longport-live.env
```

如果你希望新开的 `bash` 会话自动带上这些变量，可以把下面这行加到 `~/.bashrc` 和 `~/.bash_profile`：

```bash
[ -f "$HOME/.config/qexec/longport-live.env" ] && source "$HOME/.config/qexec/longport-live.env"
```

这样：

- 交互式 `bash` 会话会自动加载
- `bash -lc` 这类 login shell 也会自动加载
- live token 仍然不会落进 repo 根目录 `.env*`

## 3. 执行前检查

先确认 repo 根目录 `.env*` / `.envrc*` 没有 real token。

paper token 可以继续留在 repo 本地文件里，例如：

- `LONGPORT_ACCESS_TOKEN_TEST`

但 real token 要只存在于当前 shell 或 repo 外部私有文件里。

然后先跑只读 readiness：

```bash
uv run python -m quant_execution_engine config --broker longport
uv run python -m quant_execution_engine preflight --broker longport
uv run python -m quant_execution_engine account --broker longport
uv run python -m quant_execution_engine quote AAPL --broker longport
```

如果这里没过，不要继续做 real `--execute`。

`config --broker longport` 现在会直接显示：

- App Key / Secret / Access Token 的来源
- Region / Overnight 的来源

如果你想确认 real 路径是不是确实走了 `~/.config/qexec/longport-live.env`，先看这个输出就够了。

## 4. 最小 targets 文件

准备一个极小仓位、流动性足够高、你能接受的最小 smoke 目标。

例子：

```json
{
  "schema_version": 2,
  "asof": "real-smoke",
  "source": "operator-smoke",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_quantity": 1,
      "notes": "minimal real smoke"
    }
  ]
}
```

保存为：

```bash
outputs/targets/real-smoke-aapl.json
```

## 5. 最小实盘流程

### 5.1 先看 dry-run

```bash
uv run python -m quant_execution_engine rebalance outputs/targets/real-smoke-aapl.json --broker longport
```

确认：

- 输入文件正确
- symbol / market 正确
- 价格和 delta 符合预期
- risk gate 没有异常 block

### 5.2 再做最小 live execute

```bash
uv run python -m quant_execution_engine rebalance outputs/targets/real-smoke-aapl.json --broker longport --execute
```

### 5.3 立刻跟进查询

```bash
uv run python -m quant_execution_engine orders --broker longport --symbol AAPL
uv run python -m quant_execution_engine reconcile --broker longport
```

如果本地 state 里已经拿到 broker order id，再查单笔：

```bash
uv run python -m quant_execution_engine order <broker-order-id> --broker longport
```

## 6. cancel 怎么验证

当前 `rebalance --execute` 主路径默认生成的是 `MARKET` 单。

这意味着：

- 有可能迅速成交，导致这次 smoke 能证明 `submit / query / reconcile`
- 但不一定能顺便证明 `cancel`

如果 order 在你查询时仍然 open，再执行：

```bash
uv run python -m quant_execution_engine cancel <broker-order-id> --broker longport
uv run python -m quant_execution_engine reconcile --broker longport
```

如果 order 已经立即成交：

- 这次 run 只把 `submit / query / reconcile / fill recovery` 记为已覆盖
- `cancel` 留到下一次能稳定挂单的场景再补证据

不要为了“证明 cancel”而强行把这个仓库推向更复杂的 limit / algo 提交框架。

## 7. 这次 smoke 至少要保留什么证据

至少保留这些：

- 输入的 `targets.json`
- `rebalance --execute` 的终端输出
- `orders / order / reconcile / cancel` 的终端输出
- `outputs/orders/*.jsonl` 对应审计日志
- `outputs/state/*.json` 对应本地执行状态
- 一段人工备注：
  包括运行时间、symbol、broker order id、最终状态、有没有实际成交、cancel 是否被覆盖

## 8. 判定标准

这次 real smoke 至少满足下面这些条件，才算“对 real broker 又前进了一步”：

- `preflight` 通过
- `rebalance --execute` 没有在本地参数层失败
- broker order 能进入 tracked state
- `order` / `reconcile` 至少有一条能查回真实 broker 状态
- 终端输出、审计日志和 state 文件三者能对上

如果还能额外拿到：

- `cancel` 成功
- 或者 `fill` / `late fill` 的可解释状态

那这次证据就更扎实。

## 9. Alpaca 在这里的角色

Alpaca paper 仍然有价值，但角色应该很明确：

- 它是更稳定、更便宜的 regression / smoke 基线
- 它不是这个仓库的产品中心

也就是说：

- 用 Alpaca paper 练 operator workflow、回归 harness、验证 state 恢复，很合理
- 但不该因为 Alpaca 好自动化，就把仓库推向 Alpaca-first 的高级算法交易平台

当前最值钱的，仍然是把 LongPort real 的最小实盘证据链补齐。
