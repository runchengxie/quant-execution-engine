# 测试

## 默认入口

默认的测试入口为：

```bash
uv run pytest
```

该命令仅运行快速测试，默认会排除带有以下标记（marker）的测试用例：

- `integration`（集成测试）
- `e2e`（端到端测试）
- `slow`（耗时较长的慢速测试）

## 测试分层

- `tests/unit/`
  快速且相互隔离的行为测试。覆盖了命令行（CLI）路由、订单生命周期、部分成交后的恢复逻辑、执行前预检（`preflight`）、本地状态维护以及渲染器等功能。
- `tests/integration/`
  覆盖适配器和生命周期的跨模块行为测试。例如状态对账（`reconcile`）、紧急停单、状态恢复，以及在提供真实凭证或本地运行环境（runtime）时，基于真实券商后端（LongPort / IBKR）的验证。
- `tests/e2e/`
  通过子进程运行 CLI 和冒烟测试脚手架（smoke harness），进行端到端的冒烟测试。

## 常用命令

仅运行单元测试：

```bash
uv run pytest
```

仅运行端到端测试（`e2e`）：

```bash
uv run pytest -m e2e
```

仅运行集成测试：

```bash
uv run pytest -m integration
```

按需查看测试覆盖率：

```bash
uv run pytest --cov=src/quant_execution_engine --cov-report=term-missing -m 'not integration and not e2e and not slow'
```

## Broker 测试与证据矩阵

| Broker | 默认自动化覆盖 | 按需开启的自动化覆盖 | 人工监督冒烟测试 | 当前证据缺口 |
| --- | --- | --- | --- | --- |
| `alpaca-paper` | 单元测试覆盖了适配器的数据归一化、CLI 路由和执行生命周期；默认不发起真实网络请求。 | 默认无真实联网的集成测试；若需验证模拟盘凭证，需按场景手动运行。 | 可作为低成本且稳定的模拟盘回归测试与冒烟测试基线。 | 不包含实盘测试路径。 |
| `longport-paper` | 单元测试覆盖了凭证解析、LongPort 模拟盘运行环境的优先级逻辑，以及 CLI 和测试脚手架的契约。 | 在提供 `LONGPORT_ACCESS_TOKEN_TEST` 的前提下，可运行模拟盘的预检（`preflight`）与调仓（`rebalance`）路径。 | 已具备人工监督下的模拟盘测试证据，验证通过了“提交/查询/对账/撤单”的基础闭环。 | 仍需继续补充真实失败场景下的测试证据。 |
| `longport` | 单元测试覆盖了实盘保护机制、本地密钥拦截逻辑以及配置来源解析。 | 涉及 LongPort 实盘行情的集成测试依赖其相关的实盘凭证（Key/Secret/Token），凭证异常时会自动跳过。 | 需附加 `--allow-non-paper` 参数，并按照 `longport-real-smoke.md` 文档进行人工监督执行。 | 完整的实盘“提交/查询/撤单/对账”闭环尚未通过自动化的端到端验证。 |
| `ibkr-paper` | 单元测试覆盖了后端注册、运行环境配置、美股标签校验、订单与成交数据的归一化，以及冒烟测试脚手架的环境快照功能。 | 通过设置 `IBKR_ENABLE_INTEGRATION=1` 运行只读测试；`IBKR_ENABLE_MUTATION_TESTS=1` 运行提交/撤单测试；`IBKR_ENABLE_FILL_TESTS=1` 运行成交测试。 | 已具备一次本地的“无订单提交（no-order）”测试证据；具体路径请参考 `ibkr-paper-smoke.md`。 | 尚缺在有效行情下的真实券商订单、撤单和成交反馈的测试证据。 |

*注：`outputs/` 目录默认被 Git 忽略。上表中的“证据（evidence）”指的是保存在本地以供复查的运行记录，而非随代码仓库进行版本控制的固定测试夹具（fixtures）。*

可以使用以下命令检查代码路径状态与证据成熟度（evidence maturity）是否一致：

```bash
qexec evidence-maturity
qexec evidence-maturity --format json
```

## 当前测试证明了什么

- 默认的 `pytest` 命令能够确保快速的行为逻辑测试顺利通过。
- 与生命周期相关的单元测试覆盖了已跟踪订单的重试（`retry`）、重新定价（`reprice`）、状态对账（`reconcile`）、部分成交后的人工处置、等待撤单（`pending-cancel`）、迟到成交记录的恢复，以及状态诊断/清理/修复工具（`state doctor/prune/repair`）。
- 命令行（CLI）单元测试覆盖了新旧命令的路由分发以及实盘保护机制。
- 端到端测试（`e2e`）验证了 CLI 和测试脚手架在子进程中的冒烟测试行为，包括信号生成、目标持仓输出，以及操作员脚手架对非模拟盘环境的拦截路径。
- `smoke_operator_harness.py` 具备单元测试，覆盖了固定的执行流程、仅执行预检（`preflight-only`）路径、下游操作员步骤失败的处理，以及测试证据的 JSON 输出功能。
- 证据打包工具（evidence bundle）的单元测试覆盖了按运行编号（`run_id`）收集审计日志、目标清单、执行状态、测试证据及操作员备注的功能，并验证了其能够妥善处理缺失的可选文件以及跳过 `.env` 等敏感文件。
- 风控降级单元测试验证了“被禁用的风控项（`BYPASS`）”与“因缺少行情数据而降级的风控项（`BYPASS`）”之间的区分，测试了预检（`preflight`）输出的结构化详情，以及审计日志（audit JSONL）中关于降级原因的摘要信息。
- 异常恢复建议的测试涵盖了对等待撤单、过期未成交订单、部分成交订单的诊断提示，并确保查看单笔订单详情（`order`）时仅提供操作建议，不会意外触发券商后端的订单状态变更。
- `longport-paper` 已作为正式的券商后端接入。在提供 `LONGPORT_ACCESS_TOKEN_TEST` 的前提下，可执行模拟盘的预检与调仓（`preflight / rebalance`）路径。
- `ibkr-paper` 已具备单元测试，覆盖了后端注册、配置信息展示、市场与账户校验、订单与成交记录的归一化，以及冒烟测试脚手架的 IBKR 环境快照记录路径。
- `longport-paper` 目前已通过人工监督的冒烟测试，验证通过了“提交/查询/对账/撤单”的最简闭环；这是一条可复现的模拟盘测试证据链，未包含在默认的自动化测试中。
- `ibkr-paper` 拥有一次人工监督下的“无订单（no-order）”测试证据：在 WSL 环境内的 CLI 成功连接到 Windows 系统下监听 `127.0.0.1:4002` 的 IB Gateway，并跑通了配置读取、账户查询、行情获取、调仓、对账、异常查看和全部撤单等流程。但由于 IBKR 存在冲突的实盘会话（competing live session），导致 AAPL 行情返回为 0，实际产生的订单数为 0（`audit_order_count=0`）。
- LongPort 实盘已通过人工监督的只读验证，跑通了配置读取、执行预检、账户查询和行情获取流程，并确认了用户私有实盘配置的路由与实盘保护机制均能正常工作。
- 涉及 LongPort 实盘行情的测试用例，目前已支持将典型的网络、区域或凭证异常妥善处理为“跳过（skipped）”状态。

## 当前测试还没有证明什么

- 现有的测试无法单独证明 LongPort 的实盘交易（包含提交、查询、撤单、对账的完整生命周期）已通过全自动的端到端验证。
- 目前成本最低、最稳定的回归测试基线依然是 Alpaca 模拟盘；而 `longport-paper` 则是具备真实券商端测试证据链的 LongPort 模拟盘路径。
- `ibkr-paper` 目前仍缺乏在有效市场行情下真实发单的测试证据；现阶段它更适合作为依赖本地 Gateway 驱动的增量后端，而不是主要的回归测试基线。
- 实盘券商的支持成熟度，最终应以人工监督下的冒烟测试、生成的审计日志及可复查的本地证据为准。

## 运行前提

- 位于 `tests/integration/` 目录下涉及 LongPort 实盘行情的测试用例，强依赖于环境变量 `LONGPORT_APP_KEY`、`LONGPORT_APP_SECRET` 以及 `LONGPORT_ACCESS_TOKEN`。
- `tests/integration/test_ibkr_paper_integration.py` 强依赖于本地已启动并成功登录的 IB Gateway，并且需要显式开启环境变量 `IBKR_ENABLE_INTEGRATION=1`；涉及提交和撤单的用例还要求设置 `IBKR_ENABLE_MUTATION_TESTS=1`，涉及成交回报的路径则要求设置 `IBKR_ENABLE_FILL_TESTS=1`。
- `tests/e2e/` 目录下的绝大多数测试无需真实的券商凭证；当凭证缺失或网络/可用区不可达时，涉及实盘行情的用例会自动跳过。
- Alpaca 相关的测试路径默认不会发起真实的外部网络请求；如果需要进行真实的模拟盘验证，请单独配置 `ALPACA_*` 相关的环境变量并显式指定运行相应的测试场景。

## 操作员冒烟测试 (Operator Smoke Tests)

如果你希望重复验证模拟盘账户的核心执行路径与操作员命令，可以直接运行：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --execute --evidence-output outputs/evidence/ibkr-paper-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
```

如果你只想先确认依赖、凭证、账户和行情等基础条件是否正常，而不想生成目标清单或实际发单，可以先运行预检模式：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --preflight-only
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --preflight-only
```

如果你希望将某次冒烟测试的结果保存为可供复查的证据，可以添加相应的记录参数：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --evidence-output outputs/evidence/operator-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker ibkr-paper --execute --evidence-output outputs/evidence/ibkr-paper-smoke.json --operator-note "operator supervised paper smoke"
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders --evidence-output outputs/evidence/longport-paper-smoke.json
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport --allow-non-paper --execute --evidence-output outputs/evidence/longport-real-smoke.json --operator-note "operator supervised" --operator-note "cancel not covered"
```

如果上述运行成功生成了审计 `run_id`，你可以继续据此生成本地复查打包文件：

```bash
qexec evidence-pack <run-id>
qexec evidence-pack <run-id> --operator-note "reviewed terminal output"
```

如果测试流程中途在某一步失败，`--evidence-output` 也会保留部分现场证据，包括：

- 已完成的步骤
- 失败步骤的名称
- 失败步骤的退出码（exit code）和错误输出（stderr）
- 稳定的失败分类（`failure_category`）
- 保守的下一步操作提示（`next_step_hint`）
- 被跳过的步骤（`skipped_steps`），说明哪些步骤未执行及其被跳过的原因

如果测试流程顺利执行完毕，但最终已跟踪的订单状态变为本地拦截（`BLOCKED`）或其他需要操作员介入判断的状态，证据文件中还会额外保留以下信息：

- `operator_outcome_status`
- `operator_outcome_source`
- `operator_outcome_message`
- `operator_outcome_category`
- `operator_next_step_hint`
- `audit_log_path` / `audit_run_id`
- 操作员备注（`operator_notes`）

默认的冒烟测试流程会依次串联以下步骤：

1. `config`（查看配置）
2. `account`（查看账户）
3. `quote`（获取行情）
4. 写入一份最小规模的 `targets.json`
5. `rebalance --execute`（执行调仓）
6. `orders`（查看本地跟踪的订单）
7. `order`（如果本地状态中找到了最新被跟踪的订单，则查看其详情）
8. `reconcile`（状态对账）
9. `exceptions`（查看异常队列）
10. 可选的 `cancel-all`（撤销所有开启状态的订单）

如果你希望在模拟盘测试结束时，顺手清理掉本地状态中仍然处于开启（open）状态的订单，可以追加：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker alpaca-paper --execute --cleanup-open-orders
PYTHONPATH=src python project_tools/smoke_operator_harness.py --broker longport-paper --execute --cleanup-open-orders
```

此测试脚手架默认拒绝在非模拟盘环境的券商后端运行；如果你确切知道自己在做什么，并希望在实盘环境强制运行，需要额外传入 `--allow-non-paper` 参数。

- 如果你准备开始进行盈透证券模拟盘的最小闭环验证，请先阅读 [docs/ibkr-paper-smoke.md](ibkr-paper-smoke.md)。
- 如果你希望系统化地重复验证长桥证券模拟盘失败场景，建议阅读 [docs/longport-paper-failure-smoke.md](longport-paper-failure-smoke.md)。
- 如果你准备将 Alpaca 模拟盘作为日常回归测试的基线，请先阅读 [docs/alpaca-paper-smoke.md](alpaca-paper-smoke.md)。
- 如果你准备开始进行长桥证券实盘的最小闭环验证，请先阅读 [docs/longport-real-smoke.md](longport-real-smoke.md)。