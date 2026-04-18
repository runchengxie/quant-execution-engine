# 长桥（LongPort）模拟盘失败场景冒烟测试

当前 broker 支持矩阵和证据成熟度以
[current-capabilities.md](current-capabilities.md) 为准。

本文档的目标：

*   为 `longport-paper` 提供一套贴近真实运维人员的失败场景冒烟测试操作手册。
*   重点说明失败后如何观察状态、如何留存证据以及如何进行恢复。
*   明确区分哪些场景适合通过手工模拟盘复现，哪些场景更适合交由自动化回归测试来验证。

本文档刻意避免以下两点：

*   不会将当前代码库改造成一个新的券商模拟器。
*   不会为了强行构造拒单、部分成交或撤单等待（`pending-cancel`）等异常状态，去额外开发一套测试框架。

## 1. 适用时机

只有在满足以下前置条件时，执行本手册才有意义：

*   已正确配置 `LONGPORT_ACCESS_TOKEN_TEST` 环境变量。
*   `qexec config --broker longport-paper`
*   `qexec preflight --broker longport-paper`
*   `qexec account --broker longport-paper`
*   `qexec quote AAPL --broker longport-paper`

且上述基础检查均能稳定通过。
在基础检查稳定通过后，方可进入失败场景的冒烟测试。

## 2. 准备固定的证据目录

建议预先创建一组固定的输出路径，以便于重复留存证据：

```bash
mkdir -p outputs/evidence
mkdir -p outputs/targets
```

推荐的文件命名约定：

*   基线正常路径证据：
    `outputs/evidence/longport-paper-baseline.json`
*   本地阻断与人工复核证据：
    `outputs/evidence/longport-paper-blocked.json`

若需长期归档，可自行按日期建立子目录，但本系统不强制增加额外的目录管理逻辑。

## 3. 阶段一：手工可复现的失败场景冒烟测试

本阶段仅包含当前可以直接、低成本重复执行的测试场景。

### 场景 A：基线正常流程

首先需要确认基础的模拟盘流程是稳定的，否则失败场景的测试将失去对照组。

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker longport-paper \
  --execute \
  --cleanup-open-orders \
  --evidence-output outputs/evidence/longport-paper-baseline.json
```

此步骤至少需要确认：

*   从 `config` 到 `account`、`quote`、`rebalance`、`orders`、`reconcile`，最后到 `exceptions` 的整个流程能够顺利走通。
*   若成功获取到已跟踪订单的引用标识，则 `order` 命令也能正常执行。
*   `cancel-all` 命令能够成功清理模拟盘中处于开启（open）状态的订单。
*   导出的证据 JSON 文件中显示 `success=true` 且 `failed_step=null`。

在此流程稳定后，再继续补充更复杂的失败场景测试。

### 场景 B：手动紧急停单与本地阻断

此场景用于验证：

*   本地的紧急停单机制是否按预期拦截了变更类的操作。
*   运维人员能否从终端输出、异常队列以及本地状态文件中清晰地看出未下单的原因。

请先准备一个最小化的 `targets` 文件，例如：

```json
{
  "asof": "paper-failure-smoke",
  "source": "operator-smoke",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_quantity": 1,
      "notes": "manual kill switch smoke"
    }
  ]
}
```

将其保存为：

```bash
outputs/targets/longport-paper-failure-smoke.json
```

然后触发紧急停单执行一次测试：

```bash
QEXEC_KILL_SWITCH=1 qexec rebalance \
  outputs/targets/longport-paper-failure-smoke.json \
  --broker longport-paper \
  --execute
```

此处需要注意：

*   测试结果主要体现为本地阻断。
*   命令行工具不一定会返回非零的退出码。
*   核心在于确认本地风控与紧急停单的阻断原因被清晰记录。
*   将此类结果视作常规的本地阻断处理即可。

随后立即查看状态：

```bash
qexec exceptions --broker longport-paper --status blocked
qexec orders --broker longport-paper --status failure
qexec state-doctor --broker longport-paper
```

此步骤重点确认：

*   阻断原因的描述是否清晰可解释。
*   执行 `exceptions` 命令能否看到本地标记为 `BLOCKED` 的状态。
*   本地状态文件与异常队列视图的信息是否一致。

这种场景高度还原了真实运维中可能遇到的本地拦截情况，相比于强行构造一个虚假的券商拒单更具验证价值。

### 场景 C：本地状态清理与刷新

在执行完基线或阻断场景后，若怀疑本地状态存在残留数据，请先通过运维链路进行检查：

```bash
qexec reconcile --broker longport-paper
qexec exceptions --broker longport-paper
qexec state-doctor --broker longport-paper
```

若体检（`doctor`）结果提示存在安全且可修复的本地问题，再考虑执行以下修复指令：

```bash
qexec state-repair --broker longport-paper --clear-kill-switch
qexec state-repair --broker longport-paper --dedupe-fills --drop-orphan-fills
```

此步骤的重点在于验证：

*   运维人员能否遵循先查看事实、再修复本地状态的操作规范。
*   状态维护命令的作用范围是否足够克制，并能有效避免直接手工删除 `outputs/state/*.json` 文件的风险。

### 场景 D：机会型记录部分成交与撤单等待

长桥模拟盘无法保证能够稳定、低成本且可重复地手工构造出以下状态：

*   部分成交（`PARTIALLY_FILLED`）
*   撤单等待（`PENDING_CANCEL`）
*   迟到成交记录

针对此类场景，建议仅在自然遇到时顺手留存证据，不作强行构造。
若模拟盘账户在运行中自然出现了上述状态，请按以下流程留存证据：

```bash
qexec orders --broker longport-paper --status open --symbol AAPL
qexec exceptions --broker longport-paper --status partially_filled,pending_cancel --symbol AAPL
qexec order <tracked-order-ref> --broker longport-paper
qexec reconcile --broker longport-paper
```

随后根据订单状态进行最保守的处置：

*   针对部分成交（`PARTIALLY_FILLED`）：
    选择执行撤销剩余（`cancel-rest`）、继续执行剩余（`resume-remaining`）或接受部分成交（`accept-partial`）。
*   针对撤单等待（`PENDING_CANCEL`）：
    先执行对账（`reconcile`），再根据同步结果决定是否需要重试（`retry`）或改价重提（`reprice`）。

对应操作命令如下：

```bash
qexec cancel-rest <tracked-order-ref> --broker longport-paper
qexec resume-remaining <tracked-order-ref> --broker longport-paper
qexec accept-partial <tracked-order-ref> --broker longport-paper
```

## 4. 阶段二：依赖自动化回归测试的失败契约

以下失败场景目前已由自动化测试覆盖，不建议为了手工模拟盘的重复性而去强行构造：

*   调仓（`rebalance`）步骤失败后，证据文件中是否妥善保留了已执行部分的记录。
*   状态查询与对账（`orders`、`order`、`reconcile`、`exceptions`、`cancel-all`）在中途失败后，后续步骤是否正确中止。
*   调仓结束后，若未产生已跟踪的订单引用，单笔查询（`order`）步骤是否会被正确跳过。
*   对账（`reconcile`）过程中的订单查询（`get_order`）与成交明细拉取（`list_fills`）发生异常时，告警信息是否能被妥善保留。
*   发生部分成交、撤单等待或产生迟到成交记录时的状态恢复契约。

针对这些场景，建议直接运行专项回归测试：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_smoke_operator_harness.py -q
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/test_execution_foundation.py -q
```

上述两组测试目前已固化了以下关键信息的输出契约：

*   `success`
*   `failed_step`
*   `failure_category`
*   `next_step_hint`
*   `skipped_steps`

以及执行生命周期中的关键失败模式。

此处的测试分工逻辑在于：

*   模拟盘的手工冒烟测试更侧重于验证运维人员的实际操作流程与证据留存情况。
*   结构化的失败契约逻辑则应全权交由自动化测试进行反复的兜底验证。

## 5. 证据内容解析

执行 `smoke_operator_harness.py --evidence-output ...` 后，生成的证据文件至少会包含并保留以下核心字段：

*   `success`
*   `failed_step`
*   `failure_category`
*   `next_step_hint`
*   `skipped_steps`
*   `operator_outcome_status`
*   `operator_outcome_source`
*   `operator_outcome_message`
*   `operator_outcome_category`
*   `operator_next_step_hint`
*   `state_path`
*   `latest_tracked_order_ref`
*   `steps`
