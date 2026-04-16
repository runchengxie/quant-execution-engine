# 长桥 LongPort 实盘冒烟测试

这份文档的目标：

- 为 LongPort 实盘提供一套最小化的实盘冒烟操作手册
- 补齐 `submit / query / reconcile / cancel` 的证据链
- 不把实盘密钥留在仓库根目录 `.env*` / `.envrc*`

## 1. 什么时候值得开始

只有在下面这些前提满足时，才值得把 LongPort 实盘 token 加进来：

- `longport-paper` 已经跑通，就绪性和操作员流程没有明显未知数
- 你准备做一次最小、人工盯盘的实盘冒烟
- 你接受实盘路径要以极小仓位、明确留证和人工确认来推进

如果你还只是想继续打磨执行语义、CLI 行为或模拟盘失败场景，先不用急着加实盘 token。

## 2. 实盘 token 怎么放

实盘凭证只放在当前 shell 或仓库外部私有文件中。仓库根目录下这些文件不作为实盘凭证存放位置：

- `.env`
- `.env.local`
- `.envrc`
- `.envrc.local`

当前 CLI 会把仓库根目录里的 LongPort 实盘凭证视为危险配置，并在实盘 `--execute` 路径上拒绝继续。

推荐做法只有两种：

1. 在当前 shell 临时 `export`
2. `source` 一个放在仓库外的私有文件

### 推荐方式 A：当前 shell 临时导出

```bash
export LONGPORT_APP_KEY="..."
export LONGPORT_APP_SECRET="..."
export LONGPORT_ACCESS_TOKEN="..."
export LONGPORT_REGION="cn"
export LONGPORT_ENABLE_OVERNIGHT="true"
export QEXEC_ENABLE_LIVE="1"
```

### 推荐方式 B：从仓库外部私有文件导入

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
- `bash -lc` 这类登录 shell 也会自动加载
- 实盘 token 仍然不会落进仓库根目录 `.env*`

## 3. 执行前检查

先确认仓库根目录 `.env*` / `.envrc*` 里没有实盘 token。

模拟盘 token 可以继续留在仓库本地文件里，例如：

- `LONGPORT_ACCESS_TOKEN_TEST`

但实盘 token 必须只存在于当前 shell 或仓库外私有文件里。

然后先跑只读就绪性检查：

```bash
uv run python -m quant_execution_engine config --broker longport
uv run python -m quant_execution_engine preflight --broker longport
uv run python -m quant_execution_engine account --broker longport
uv run python -m quant_execution_engine quote AAPL --broker longport
```

这里只读检查通过后，再继续实盘 `--execute`。

`config --broker longport` 现在会直接显示：

- App Key / Secret / Access Token 的来源
- Region / Overnight 的来源

确认实盘路径是否走了 `~/.config/qexec/longport-live.env`，直接看这段输出即可。

## 4. 最小 `targets` 文件

准备一个极小仓位、流动性足够高、你能接受的最小冒烟目标。

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

### 5.1 先看预演

```bash
uv run python -m quant_execution_engine rebalance outputs/targets/real-smoke-aapl.json --broker longport
```

确认：

- 输入文件正确
- `symbol` / `market` 正确
- 价格和 delta 符合预期
- 风控门禁没有异常阻断

### 5.2 再做最小实盘执行

```bash
uv run python -m quant_execution_engine rebalance outputs/targets/real-smoke-aapl.json --broker longport --execute
```

### 5.3 立刻跟进查询

```bash
uv run python -m quant_execution_engine orders --broker longport --symbol AAPL
uv run python -m quant_execution_engine reconcile --broker longport
```

如果本地状态里已经拿到券商订单 ID，再查单笔：

```bash
uv run python -m quant_execution_engine order <broker-order-id> --broker longport
```

## 6. `cancel` 怎么验证

当前 `rebalance --execute` 主路径默认生成的是 `MARKET` 单。

这意味着：

- 有可能很快成交，从而证明 `submit / query / reconcile`
- 但不一定能顺手证明 `cancel`

如果订单在你查询时仍然 open，再执行：

```bash
uv run python -m quant_execution_engine cancel <broker-order-id> --broker longport
uv run python -m quant_execution_engine reconcile --broker longport
```

如果订单已经立即成交：

- 这次运行只把 `submit / query / reconcile / fill recovery` 记为已覆盖
- `cancel` 留到下一次能稳定挂单的场景再补证据

`cancel` 证据可以留到下一次更适合挂单的场景补齐。当前范围不扩展到更复杂的 limit / algo 提交框架。

## 7. 这次冒烟至少要保留什么证据

至少保留这些：

- 输入的 `targets.json`
- `rebalance --execute` 的终端输出
- `orders / order / reconcile / cancel` 的终端输出
- `outputs/orders/*.jsonl` 对应的审计日志
- `outputs/state/*.json` 对应的本地执行状态
- 一段人工备注：包括运行时间、symbol、券商订单 ID、最终状态、是否实际成交、是否覆盖了 `cancel`

如果你想把这些证据一次性沉淀成结构化 JSON，可以直接跑：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker longport \
  --allow-non-paper \
  --execute \
  --evidence-output outputs/evidence/longport-real-smoke.json \
  --operator-note "operator supervised live smoke" \
  --operator-note "cancel not covered"
```

这份 evidence 现在会额外保留：

- `audit_log_path` / `audit_run_id`
- `state_path`
- `latest_tracked_order_ref`
- `operator_notes`

## 8. 判定标准

这次实盘冒烟至少满足下面这些条件，才算“对实盘券商又前进了一步”：

- `preflight` 通过
- `rebalance --execute` 没有在本地参数层失败
- 券商订单能进入已跟踪状态
- `order` / `reconcile` 至少有一条能查回真实券商状态
- 终端输出、审计日志和状态文件三者能对上

如果还能额外拿到：

- `cancel` 成功
- 或者 `fill` / `late fill` 的可解释状态

那这次证据就更扎实。

## 9. Alpaca 在这里的角色

Alpaca 模拟盘仍然有价值，但角色应该很明确：

- 它是更稳定、更便宜的回归 / 冒烟基线
- 它在当前仓库里承担回归和冒烟基线角色

也就是说：

- 用 Alpaca 模拟盘练操作员流程、回归工装、验证状态恢复，很合理
- 仓库当前也不扩展到 Alpaca-first 的高级算法交易平台方向

当前最值钱的，仍然是把 LongPort 实盘的最小证据链补齐。
