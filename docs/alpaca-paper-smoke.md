# Alpaca 模拟盘冒烟测试（最小操作路径）

本文档提供了 Alpaca 模拟盘（`alpaca-paper`）的最小可复查冒烟测试路径，旨在帮助你快速确认以下事项：

*   API 凭证加载正常；
*   核心操作命令链路（如 `config`、`preflight`、`account`、`quote`、带 `--execute` 参数的 `rebalance`、`orders` 以及 `reconcile`）已成功连通；
*   能够生成并留存本地的测试证据（Evidence）JSON 文件，以便后续复查。

> 定位说明：当前我们将 `alpaca-paper` 作为低成本、稳定且可重复的模拟盘回归测试基线使用，该路径不涉及实盘交易。

## 1. 准备依赖

```bash
uv sync --group dev --extra cli --extra alpaca
```

## 2. 准备环境变量

请至少提供一组 Alpaca 模拟盘的 API 凭证：

*   `ALPACA_API_KEY` 或 `APCA_API_KEY_ID`
*   `ALPACA_SECRET_KEY` 或 `APCA_API_SECRET_KEY`

建议在当前的命令行终端（Shell）中临时导出（`export`）这些变量，避免将凭证硬编码并遗留在代码仓库的本地配置文件中。

## 3. 执行只读预检查（推荐）

```bash
qexec config --broker alpaca-paper
qexec preflight --broker alpaca-paper
qexec account --broker alpaca-paper --format json
qexec quote AAPL --broker alpaca-paper
```

如果在上述步骤发生失败，请先排查并修复凭证配置、网络连接或市场行情（Market Data）的权限问题，切勿直接进入带有 `--execute` 参数的正式下单环节。

## 4. 最小执行路径

请准备一个符合目标持仓规范（详情请参考 `targets.md`）的 `targets.json` 文件（例如将其存放在 `outputs/targets/alpaca-paper-smoke.json`），然后依次执行以下命令：

```bash
qexec rebalance outputs/targets/alpaca-paper-smoke.json --broker alpaca-paper
qexec rebalance outputs/targets/alpaca-paper-smoke.json --broker alpaca-paper --execute
qexec orders --broker alpaca-paper --status open
qexec reconcile --broker alpaca-paper
qexec exceptions --broker alpaca-paper --status failure
```

如果你只想通过自动化脚本来验证固定的操作流程，也可以直接使用配套的冒烟测试脚手架（Harness）：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/alpaca-paper-smoke.json
```

## 5. 建议留存的测试证据

建议在测试完成后，至少保留以下文件记录：

*   `outputs/orders/*.jsonl`（调仓审计日志）
*   `outputs/state/*.json`（本地执行状态文件）
*   `outputs/evidence/alpaca-paper-smoke.json`（如果在脚手架脚本中指定了 `--evidence-output` 参数）

在审计日志中获取到本次运行的编号（`audit_run_id`）后，建议再生成一个复查压缩包：

```bash
qexec evidence-pack <audit-run-id>
qexec evidence-pack <audit-run-id> --operator-note "alpaca 模拟盘冒烟测试已复查"
```

打包后的证据文件默认将输出至：`outputs/evidence-bundles/<audit-run-id>` 目录下。

## 6. 常见失败原因排查

*   凭证异常：环境变量凭证缺失，或 API Key 与 Secret 不匹配。
*   权限异常：模拟盘账户状态异常，或缺乏获取相关标的行情的权限。
*   市场状态：当前市场状态（如处于非交易时段、熔断停牌等）导致报价或下单行为与预期不符。
*   本地状态残留：本地执行状态中残留有未处理的已跟踪订单（Tracked Order）。遇到此情况，需要先执行全部撤单命令（`qexec cancel-all --broker alpaca-paper`），或先执行对账命令（`qexec reconcile`）同步最新状态后，再尝试重新运行测试。