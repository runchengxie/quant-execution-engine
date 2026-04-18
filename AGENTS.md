# AGENTS

## Repo Scope

- 这是一个 execution-only 仓库。
- research、AI、回测、数据导入已经移除，不要再按 monorepo/monolith 假设补回这些层。

## Environment

- 使用 `uv` 作为默认入口。
- 常用初始化命令：`uv sync --group dev --extra cli`
- 常用测试命令：`uv run pytest`

## Testing

- 默认测试只跑快速单元测试。
- `integration` 和 `e2e` 需要显式选择：
  - `uv run pytest -m integration`
  - `uv run pytest -m e2e`
- 覆盖率是按需视角，不应绑死在默认 `pytest` 入口。
- 优先写行为测试，不要堆源码字符串、文件存在性之类的低价值静态断言。

## Current Functional Caveats

- `qexec rebalance --execute` 在 LongPort real、`longport-paper`、Alpaca paper 和 `ibkr-paper` 上都有 broker-backed submit/query/cancel/reconcile 代码路径。
- LongPort real broker 的自动化端到端证据仍弱于 paper smoke；real broker 仍应按 operator-supervised 路径使用。
- `ibkr-paper` 是本地 IB Gateway over TWS API 依赖型 paper backend，当前只支持 US equities 最小切片；已有 no-order evidence 证明 Gateway/account/reconcile 路径可达，但有效行情下的 broker order / cancel / fill 证据仍待补齐。
- `longport-paper` 依赖 `LONGPORT_ACCESS_TOKEN_TEST`；LongPort real 依赖 `LONGPORT_ACCESS_TOKEN`。
- `ibkr-paper` 依赖本地已启动并登录的 IB Gateway；常用环境变量是 `IBKR_HOST`、`IBKR_PORT` / `IBKR_PORT_PAPER`、`IBKR_CLIENT_ID`，可选 `IBKR_ACCOUNT_ID`。
- `longport-paper` 默认优先读取 repo 根目录 `.env` / `.env.local`；LongPort real 默认优先读取 `~/.config/qexec/longport-live.env`。
- `QEXEC_ENABLE_LIVE` 会先读当前进程环境变量；如果没设置，再回退到 `~/.config/qexec/longport-live.env`。
- `qexec config` 会显示 LongPort App Key / Secret / Token / Region / Overnight 的命中来源，便于确认当前到底走的是 paper 还是 user-private live 配置。
- `qexec rebalance --account` 当前做的是 account/profile label 解析与 fail-fast 校验，不是多账户路由。
- LongPort real、`longport-paper`、Alpaca paper 和 `ibkr-paper` 当前 adapter 仍按单账户语义运行；unsupported label 会直接报错。
- `retry` 只支持零成交 terminal tracked order；部分成交要走 `cancel-rest`、`resume-remaining` 或 `accept-partial`。
- `orders` / `exceptions` / `order` 都是本地 tracked-state 视图，不是 broker 全量订单视图。
- 调仓输入只接受 canonical `targets.json`。

## Outputs

- 调仓审计日志输出到 `outputs/orders/*.jsonl`。
- 本地执行状态输出到 `outputs/state/*.json`。
- smoke evidence 输出到 `outputs/evidence/*.json`（例如 `smoke_operator_harness.py --evidence-output ...`）。
- evidence bundle 输出到 `outputs/evidence-bundles/*`（通过 `qexec evidence-pack <run-id>` 生成）。
