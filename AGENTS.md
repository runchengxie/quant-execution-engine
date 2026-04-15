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

- `qexec rebalance --execute` 在 LongPort 和 Alpaca paper 上都会走 broker-backed submit/query/cancel/reconcile 路径，但 LongPort real broker 的自动化端到端证据仍弱于 Alpaca paper smoke；real broker 仍应按 operator-supervised 路径使用。
- `qexec rebalance --account` 当前做的是 account/profile label 解析与 fail-fast 校验，不是多账户路由。
- 当前 adapter 仍按单账户语义运行；unsupported label 会直接报错。
- `retry` 只支持零成交 terminal tracked order；部分成交要走 `cancel-rest`、`resume-remaining` 或 `accept-partial`。
- `orders` / `exceptions` / `order` 都是本地 tracked-state 视图，不是 broker 全量订单视图。
- 调仓输入只接受 canonical schema-v2 `targets.json`。

## Outputs

- 调仓审计日志输出到 `outputs/orders/*.jsonl`。
- 本地执行状态输出到 `outputs/state/*.json`。
