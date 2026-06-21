# 命令行接口（CLI）使用说明

## 命令入口

推荐的命令入口：

```bash
qexec
```

为了向下兼容，也可以使用：

```bash
stockq
```

在开发环境下，你也可以直接通过 Python 模块执行：

```bash
PYTHONPATH=src python -m quant_execution_engine
```

请根据需要连接的券商安装相应的依赖包：

```bash
# 长桥证券
uv sync --group dev --extra cli --extra longport
# Alpaca
uv sync --group dev --extra cli --extra alpaca
# 盈透证券（IBKR）
uv sync --group dev --extra cli --extra ibkr
# 安装所有券商依赖
uv sync --group dev --extra cli --extra full
```

如果未在配置文件（`config/config.yaml`）中显式指定券商后端（`broker.backend`），则在每次执行命令时都必须通过 `--broker` 参数进行指定。

## 子命令

### `config`

显示当前配置的券商后端、风控拦截机制、紧急停单状态以及相关凭证的摘要信息。

```bash
qexec config --broker longport-paper
qexec config --broker alpaca-paper
qexec config --broker ibkr-paper
```

对于长桥，该命令还会详细列出各项核心凭证与参数（App Key / Secret / Access Token / Region / Overnight）的配置读取来源，方便你排查当前使用的是代码库本地的模拟盘配置，还是用户私有目录下的实盘配置。

对于盈透模拟盘（`ibkr-paper`），该命令会显示本地网关的主机地址、端口、客户 ID、账户 ID 及超时时间，并标明当前的运行环境设定（基于本地 IB Gateway 和 TWS API）。

附加 `--check-gates` 可以只打印当前生效的风险门控阈值与紧急停单状态，适合在盘前快速复核：

```bash
qexec config --broker longport-paper --check-gates
qexec config --broker longport --check-gates
```

### `evidence-maturity`

查看各券商接入代码的成熟度、最新的测试证据、存在的功能缺口以及下一步的冒烟测试建议。

```bash
qexec evidence-maturity
qexec evidence-maturity --format json
```

该命令仅读取本地的测试证据文件（`outputs/evidence/*.json`）和券商的能力配置，不会向券商后台发起全量订单扫描，也不依赖任何外部数据库。

### `evidence-pack`

根据审计的运行编号（`run_id`），将某次执行产生的所有复查证据打包归档。

```bash
qexec evidence-pack <run-id>
qexec evidence-pack <run-id> --output-dir outputs/review
qexec evidence-pack <run-id> --operator-note '终端输出已人工复查'
```

生成的 `manifest.json` 现在除了归档清单，还会附带 `trace_summary`，用于快速查看本次打包里追踪记录快照的数量、警告数量和订单级摘要，而不必先打开完整的 `trace/order_traces.json`。CLI 终端输出也会同步显示一行简要的 trace 统计。

打包结果默认输出到 `outputs/evidence-bundles/<run-id>` 目录下。系统会生成一份清单文件，记录审计日志、目标持仓文件、本地状态、冒烟测试证据、按订单聚合的追踪记录快照以及操作员备注的包含、缺失或跳过状态；同时，安全机制会确保 `.env*` 等包含敏感信息的凭证文件不会被打包进去。

### `preflight`

在不改变券商实际账户状态的前提下，运行执行前的就绪性检查。

```bash
qexec preflight --broker longport-paper
qexec preflight AAPL MSFT --broker longport-paper
qexec preflight --broker alpaca-paper
qexec preflight --broker ibkr-paper
```

当前的预检项包括：

- 券商接口能力矩阵
- 实盘执行保护机制状态
- 手动紧急停单状态
- 本地执行状态的紧急停单状态
- 账户解析是否正常
- 账户资产快照能否获取
- 行情、订单簿深度与成交量数据的可达性
- 检查已配置的依赖市场数据的风控项，判断是否会因为买卖盘或日成交量数据缺失而在正式执行时被降级跳过。

对于盈透模拟盘（`ibkr-paper`），这些检查能直接反映本地 IB Gateway 的连通性、账户解析情况和行情获取权限；如果发生失败，网关的网络连通性错误会直接体现在检查结果中。

### `account`

查询账户的资金与持仓概览。

```bash
qexec account --broker longport-paper
qexec account --broker longport-paper --format json
qexec account --broker longport-paper --funds
qexec account --broker longport-paper --positions
qexec account --broker alpaca-paper
qexec account --broker ibkr-paper
qexec account --account main
```

### `quote`

查询实时的市场行情。

```bash
qexec quote AAPL 700.HK --broker longport-paper
qexec quote AAPL --broker alpaca-paper
qexec quote AAPL --broker ibkr-paper
```

注意：当前盈透模拟盘（`ibkr-paper`）仅支持美股正股的基础行情；如果传入类似 `700.HK` 这类非美股代码，系统会直接报错拦截。

### `orders`

查看本地执行状态中已被系统追踪的券商订单。

```bash
qexec orders --broker longport-paper --status open
qexec orders --broker longport-paper --symbol AAPL
```

你可以通过状态（如 `open`、`failure`、`terminal`）或标的代码（如 `AAPL`）进行过滤。
注意：此命令仅展示本地执行引擎已追踪的订单。

### `broker-orders`

查看券商原生的只读订单历史视图（当前仅在支持该能力的后端上可用，例如长桥）。

```bash
qexec broker-orders --broker longport-paper
qexec broker-orders --broker longport --symbol AAPL --status filled
qexec broker-orders --broker longport --order-id 123456789 --format json
```

这是一条券商端的只读查询路径，用于辅助排障、审计与复盘；它不替代本地追踪状态，也不改变 `orders` 命令的语义。

### `broker-fills`

查看券商原生的只读成交历史视图（当前仅在支持该能力的后端上可用，例如长桥）。

```bash
qexec broker-fills --broker longport-paper
qexec broker-fills --broker longport --symbol AAPL
qexec broker-fills --broker longport --order-id 123456789 --format json
```

此命令返回的是券商端成交记录，用于和本地成交记录或追踪状态对照排查。

### `exceptions`

查看本地执行状态中的异常订单队列。

```bash
qexec exceptions --broker longport-paper
qexec exceptions --broker longport-paper --status blocked,failed
```

用于快速定位需要人工干预的订单。默认展示被本地风控拦截（`blocked`）、提交失败（`failed`）、被券商拒绝（`rejected`）、过期（`expired`）、部分成交（`partially_filled`）或正在等待撤单结果（`pending_cancel`）的追踪记录。

### `order`

查询单笔追踪订单的完整生命周期详情。

```bash
qexec order <broker-order-id> --broker longport-paper
```

你可以传入券商订单 ID、本地子订单 ID 或客户端订单 ID 作为引用凭证。系统会输出该订单的交易意图、母订单与子订单关系、详细的成交回报流水，以及针对当前异常状态的诊断与下一步操作建议。

### `trace-order`

查看某一条追踪订单的联合时间线：本地追踪状态的母子订单尝试、成交事件，以及在支持的后端上补充券商端的只读历史记录。

```bash
qexec trace-order <broker-order-id> --broker longport-paper
qexec trace-order <child-order-id> --broker longport --format json
```

这个命令不会修改任何状态；它的目标是把本地追踪到的事实和券商端只读历史记录放到同一个复查视图里。

### `rebalance`

核心调仓指令。基于标准目标持仓文件生成执行计划，并负责实际下单。

```bash
# 默认行为：仅生成调仓差异预览（预演）
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper

# 附加 --execute 参数：正式向券商提交订单
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --execute

# 附加 --target-gross-exposure 参数：在命令行层面覆盖目标的总风险敞口倍率
qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper --target-gross-exposure 0.8
```

输入文件必须严格符合 [targets.md](targets.md) 中定义的 `targets.json` 格式。
*安全门禁：若要在实盘环境（如 `--broker longport`）下使用 `--execute` 参数，当前终端会话必须显式设置环境变量 `QEXEC_ENABLE_LIVE=1`。*

### `reconcile`

手动触发与券商后台的状态对账。

```bash
qexec reconcile --broker longport-paper
```

系统会主动从券商拉取最新的活跃订单状态与成交回报流水，将其与本地状态进行比对与合并，并输出详细的差异与状态变更摘要。在处理异常订单或执行干预操作前，强烈建议先运行此命令以同步最新事实。

### `cancel` 与 `cancel-all`

撤销追踪中的订单。

```bash
# 撤销单笔订单
qexec cancel <broker-order-id> --broker longport-paper

# 批量撤销当前账户下所有本地已追踪且处于开启状态的订单
qexec cancel-all --broker longport-paper
```

`cancel-all` 极其适合用于紧急情况下的快速干预，或在模拟盘冒烟测试结束后的环境清理收尾。

### `retry` / `reprice` / `retry-stale`（订单干预与重试）

对挂单或失败的订单进行主动干预。

```bash
# 重新提交一笔零成交且已失败或被拒绝的订单
qexec retry <broker-order-id> --broker longport-paper

# 对一笔仍在开启状态的限价单进行改价（系统会先执行撤单，再以新价格发起新的子订单）
qexec reprice <broker-order-id> --limit-price 155.50 --broker longport-paper

# 批量处理过期挂单：撤销在本地停留超过指定时长（默认 5 分钟）且零成交的挂单，并重新发起提交
qexec retry-stale --older-than-minutes 15 --broker longport-paper
```

### `cancel-rest` / `resume-remaining` / `accept-partial`（部分成交处理）

当订单发生部分成交时，系统会将其停留在需要人工介入的状态。你可以使用以下专项命令进行处理：

```bash
# 1. 撤销剩余未成交的部分
qexec cancel-rest <broker-order-id> --broker longport-paper

# 2. 针对剩余未成交的数量，生成并提交一笔新的子订单继续执行
qexec resume-remaining <broker-order-id> --broker longport-paper

# 3. 接受当前的局部成交结果，放弃后续执行，并在本地将该订单标记为完结
qexec accept-partial <broker-order-id> --broker longport-paper
```

### `state-doctor` / `state-prune` / `state-repair`（本地状态维护）

维护位于 `outputs/state/` 目录下的本地执行状态文件一致性。

```bash
# 状态体检：检查本地状态文件是否存在数据孤岛、母子订单汇总数据不一致等隐患
qexec state-doctor --broker longport-paper

# 状态清理：清理已完结且超过指定天数（默认 30 天）的旧订单记录
# 注意：必须附加 --apply 才会真正执行删除，否则仅打印清理预览
qexec state-prune --older-than-days 45 --apply --broker longport-paper

# 状态修复：执行安全的本地一致性修复
# 例如：清除紧急停单标记、去重成交记录、移除游离数据，或重新计算母订单进度
qexec state-repair --clear-kill-switch --dedupe-fills --recompute-parent-aggregates --broker longport-paper
```

`state-repair` 当前支持的修复开关：

- `--clear-kill-switch`
  清除本地紧急停单标记并重置连续失败计数。
- `--dedupe-fills`
  去除本地执行状态中的重复成交记录。
- `--drop-orphan-fills`
  移除无法映射到任何已追踪订单的游离成交记录。
- `--drop-orphan-terminal-broker-orders`
  移除未被任何子订单引用、且已经处于终态的游离券商订单记录。
- `--recompute-parent-aggregates`
  根据本地子订单、券商订单和成交记录重新计算母订单的成交数量、剩余数量和汇总状态。

### `report`

从本地的证据打包目录（`outputs/evidence-bundles/`）中读取历次执行的审计证据，生成操作员可读的摘要报表。

```bash
# 列出所有可用的执行运行记录（最新在前）
qexec report

# 按券商过滤
qexec report --broker longport-paper

# 只展示最近 5 次运行
qexec report --broker longport-paper --last-n 5

# 查看某次运行的详细报告（包括逐笔订单追踪摘要）
qexec report --run-id 20260621_abc123
```

该命令不需要预先运行 `evidence-pack`，直接读取已存在的 `manifest.json`（如有）。适合在复盘、排障或操作员交接时快速了解历史执行概况。

### `health`

快速运行一次只读健康检查，合并 preflight 与 state-doctor 的结果，输出统一的"健康 / 不健康"判断。

```bash
qexec health --broker longport-paper
qexec health --broker ibkr-paper
```

检查内容包括：
- 券商接口可达性、账户解析、行情获取
- 实盘保护机制状态
- 本地执行状态一致性
- 紧急停单状态

所有检查均为只读操作，不会提交订单或修改本地状态。适合作为盘前检查或 Makefile `make health` 目标的基础命令。
