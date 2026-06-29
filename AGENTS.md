# AGENTS

## 仓库范围

- 这是一个只负责交易执行的仓库。
- 策略研究、AI 信号、历史回测和原始数据导入已经移除。不要把这些模块重新加回本仓库。

## 环境

- 使用 `uv` 作为默认入口。
- 常用初始化命令：`uv sync --group dev --extra cli`
- 常用测试命令：`uv run pytest`

## 测试

- 默认测试只跑快速单元测试。
- `integration` 和 `e2e` 需要显式选择：
  - `uv run pytest -m integration`
  - `uv run pytest -m e2e`
- 覆盖率是按需视角，不应绑死在默认 `pytest` 入口。
- Ruff、ty 和默认快速测试是当前基础门禁。`make quality` 会额外运行 Pyright 和 mypy；顶层委托检查的 `release_typecheck` 运行 Pyright，`mypy_advisory` 单独保留。默认
  `pytest` 只说明快速行为回归通过，合并前仍需按改动范围运行完整质量门控。
- 优先写行为测试，不要堆源码字符串、文件存在性之类的低价值静态断言。

## 当前功能注意事项

- 当前完整支持矩阵、凭证来源规则、证据成熟度和已知限制以 `docs/current-capabilities.md` 为准。
- 长桥实盘的自动化端到端证据仍弱于模拟盘冒烟测试；实盘操作必须由操作员按文档监督执行。
- `ibkr-paper` 依赖本地 IB Gateway 和 TWS API，目前只支持美股正股的最小切片；已有无报单证据证明 Gateway/account/reconcile 路径可达，但有效行情下的券商报单、撤单和成交证据仍待补齐。
- `longport-paper` 依赖 `LONGPORT_ACCESS_TOKEN_TEST`；LongPort real 依赖 `LONGPORT_ACCESS_TOKEN`。
- `ibkr-paper` 依赖本地已启动并登录的 IB Gateway；常用环境变量是 `IBKR_HOST`、`IBKR_PORT` / `IBKR_PORT_PAPER`、`IBKR_CLIENT_ID`，可选 `IBKR_ACCOUNT_ID`。
- `longport-paper` 默认优先读取 repo 根目录 `.env` / `.env.local`；LongPort real token 不得放在 repo-local `.env*` / `.envrc*`。
- `QEXEC_ENABLE_LIVE` 会先读当前进程环境变量；如果没设置，再回退到 `~/.config/qexec/longport-live.env`。
- `qexec config` 会显示 LongPort App Key / Secret / Token / Region / Overnight 的命中来源，便于确认当前到底走的是模拟盘配置还是用户私有实盘配置。
- `qexec rebalance --account` 当前只做 account/profile 标签解析与快速失败校验，不提供多账户路由。
- LongPort real、`longport-paper`、Alpaca paper 和 `ibkr-paper` 当前 adapter 仍按单账户语义运行；不支持的标签会直接报错。
- `retry` 只支持零成交的终态本地追踪订单；部分成交要走 `cancel-rest`、`resume-remaining` 或 `accept-partial`。
- `orders` / `exceptions` / `order` 都是本地追踪状态视图；券商全量订单视图使用只读券商查询命令。
- 调仓输入只接受标准 `targets.json`。

## 输出

- 调仓审计日志输出到 `outputs/orders/*.jsonl`。
- 本地执行状态输出到 `outputs/state/*.json`。
- 冒烟测试证据输出到 `outputs/evidence/*.json`（例如 `smoke_operator_harness.py --evidence-output ...`）。
- 证据包输出到 `outputs/evidence-bundles/*`（通过 `qexec evidence-pack <run-id>` 生成）。
