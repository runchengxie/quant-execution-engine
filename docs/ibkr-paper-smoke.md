# 盈透证券（IBKR）模拟盘冒烟测试

本文档旨在说明以下目标：

- 为盈透模拟盘（`ibkr-paper`）提供一套最小化的人工监督操作手册。
- 明确本地运行 `IB Gateway` 配合 `TWS API` 是先决条件（切勿将盈透证券视作纯云端接入的券商后端）。
- 为配置检查、预检、账户查询、行情获取、执行调仓以及状态对账等核心命令，提供一条可复查的模拟盘验证路径。

## 1. 当前边界

当前盈透证券模拟盘的功能范围进行了严格限制：

- 仅支持模拟盘，不支持实盘。
- 目前仅支持美股正股的基础交易闭环。
- 采用单账户逻辑运行，账户参数仅接受 `main`。
- 工作区内已有人工监督下（由WSL连接Windows网关）的测试证据记录样例。
- 该样例已证明网关连通、账户查询和对账路径可用，提交、成交和撤单的完整证据仍需在后续具备有效行情的测试中补齐。

## 2. 运行前提

至少需要准备以下条件：

- 本地已安装并可启动的 `IB Gateway`（盈透网关）。
- 一个可正常登录的盈透模拟盘账户。
- 已在网关设置中启用 `TWS API`（即Socket API）功能。

可选的运行环境变量配置：

```bash
export IBKR_HOST="127.0.0.1"
export IBKR_PORT_PAPER="4002"
export IBKR_CLIENT_ID="1"
# 可选：如果网关下只有一个账户，可以不设置此项
export IBKR_ACCOUNT_ID="DU123456"
export IBKR_CONNECT_TIMEOUT_SECONDS="5"
```

当前执行引擎会优先读取以下环境变量：

- `IBKR_HOST`
- `IBKR_PORT`（如果未设置，则降级读取 `IBKR_PORT_PAPER`）
- `IBKR_CLIENT_ID`
- `IBKR_ACCOUNT_ID`
- `IBKR_CONNECT_TIMEOUT_SECONDS`

## 3. 网关设置

启动并登录模拟盘网关后，请务必确认以下API设置：

- API功能已开启。
- 监听端口与环境变量配置一致。
- 当前机器可以访问该端口（通常为 `127.0.0.1`）。
- 当前登录的是模拟盘会话，而非实盘。
- 如果代码运行在WSL且网关运行在Windows宿主机上，请优先尝试 `127.0.0.1:4002`；若在NAT模式下无法连接，再将环境变量修改为Windows主机的IP地址。
- 网关不能处于API只读模式，否则盈透客户端会弹出写入权限提示并拒绝模拟盘下单。
- 盈透需要为当前的API会话返回有效的市场行情。如果因实盘会话冲突导致价格为零，执行调仓命令时会跳过订单提交，仅留下无报单的测试记录。

如果预检命令提示主机或端口无法连接，请先排查网关是否已在本机成功启动并处于监听状态。

## 4. 优先执行只读检查

```bash
qexec config --broker ibkr-paper
qexec preflight --broker ibkr-paper
qexec account --broker ibkr-paper
qexec quote AAPL --broker ibkr-paper
```

重点确认以下结果：

- 配置查询命令已显示正确的主机、模拟盘端口、客户编号和账户编号。
- 预检命令没有报出网关连通性、账户解析或行情获取失败的错误。
- 账户查询命令能正常返回模拟盘账户概览。
- 行情查询命令能获取到对应美股的实时报价。

## 5. 最小化目标持仓文件

```json
{
  "asof": "ibkr-paper-smoke",
  "source": "operator-smoke",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_quantity": 1,
      "notes": "minimal ibkr paper smoke"
    }
  ]
}
```

请将上述内容保存为：

```bash
outputs/targets/ibkr-paper-smoke.json
```

## 6. 最小化执行流程

### 6.1 执行调仓预演

```bash
qexec rebalance outputs/targets/ibkr-paper-smoke.json --broker ibkr-paper
```

### 6.2 执行模拟盘下单

```bash
qexec rebalance outputs/targets/ibkr-paper-smoke.json --broker ibkr-paper --execute
```

### 6.3 立即跟进状态查询

```bash
qexec orders --broker ibkr-paper --symbol AAPL
qexec reconcile --broker ibkr-paper
```

如果本地状态中已经记录了券商的订单编号，可以进一步查询单笔订单详情：

```bash
qexec order <broker-order-id> --broker ibkr-paper
```

如果该订单仍处于开启状态，可以验证撤单逻辑：

```bash
qexec cancel <broker-order-id> --broker ibkr-paper
qexec reconcile --broker ibkr-paper
```

## 7. 使用冒烟测试脚手架

如果你希望通过自动化脚本验证固定流程，可以使用冒烟测试脚手架。

仅运行预检：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker ibkr-paper \
  --preflight-only
```

直接执行最小化的模拟盘工作流并留存证据：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker ibkr-paper \
  --execute \
  --evidence-output outputs/evidence/ibkr-paper-smoke.json \
  --operator-note 'operator supervised paper smoke'
```

## 8. 测试证据留存规范

完成本次冒烟测试后，建议至少留存以下内容：

- 输入的持仓目标文件。
- 各项命令（配置、预检、账户、行情、调仓、对账）的终端输出记录。
- 订单查询和撤单命令的终端输出（如果本次测试覆盖了该环节）。
- 对应的审计日志文件（`outputs/orders/*.jsonl`）。
- 本地执行状态文件（`outputs/state/*.json`）。
- 使用测试脚手架生成的测试证据文件（`outputs/evidence/ibkr-paper-smoke.json`）。
- 一段人工复查备注：包含运行时间、网关地址与端口、账户信息、测试标的、券商订单编号、最终状态，以及是否实际覆盖了撤单或成交环节。

如果遇到行情为零或网关拒绝写入API的情况，也必须在测试证据或人工备注中写明。这类记录可用于证明运行时的网络可达性，但不能替代真实的提交、成交或撤单证据。

注：输出目录默认被Git版本控制忽略，此处提到的测试证据是指留在本地供后续复查的档案，并非随代码库提交的测试用例夹具。

## 9. 成熟度判断标准

当前阶段，不应将盈透模拟盘视为与 Alpaca 模拟盘同等成熟的验证路径。

针对盈透模拟盘，目前更合理的完成度判断标准为：

- 只读检查功能表现稳定。
- 能够跑通最小化的调仓下单路径。
- 订单查询、对账和撤单等操作能够在本地状态中被清晰复查。
- 至少保留一份人工监督下的测试证据样例。

由于目前仅有一份无报单的测试记录（流程已跑通并生成了审计日志，但因苹果公司股价为零导致实际记录的报单数为零），因此现阶段建议将盈透模拟盘定位为：网关已连通、代码逻辑已闭环，但真实的券商订单证据链仍待补齐的后端。下一次在有效行情下的模拟盘测试，必须补齐提交、查询、对账、撤单或成交的验证证据。

在完成一次包含有效行情的冒烟测试后，请先通过以下命令确认当前的证据成熟度状态：

```bash
qexec evidence-maturity
```

随后使用对应的审计运行编号生成复查打包文件：

```bash
qexec evidence-pack <audit-run-id>
qexec evidence-pack <audit-run-id> --operator-note 'IBKR paper order evidence reviewed'
```

如果测试证据打包文件中缺少冒烟测试JSON记录、审计日志或状态快照文件，本次运行只能视作部分证据，系统不会将该后端提升为完整成熟的验证路径。
