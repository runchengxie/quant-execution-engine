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

- `qexec rebalance --execute` 当前会进入 live-mode 路径并写审计日志，但 broker submit 分支仍返回模拟 `order_id`，没有真正提交 LongPort 订单。
- `qexec rebalance --account` 目前只记录到日志里，不会切换实际 broker 账户。
- 调仓输入只接受 canonical schema-v2 `targets.json`。

## Outputs

- 调仓审计日志输出到 `outputs/orders/*.jsonl`。
