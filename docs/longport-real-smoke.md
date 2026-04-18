# 长桥（LongPort）实盘冒烟测试指南

本文档旨在：
* 为长桥实盘环境提供一套最小化的人工冒烟测试操作手册
* 补齐从提交订单、查询、对账到撤单的完整测试证据链
* 确保实盘密钥不会残留在代码仓库根目录的本地配置文件中

## 1. 何时建议开始实盘测试

只有在满足以下前提条件时，才建议引入实盘凭证：

* 长桥模拟盘流程已完全跑通，系统就绪状态和操作员流转逻辑已无明显盲区
* 准备好进行一次最小规模、且需要人工全程盯盘的实盘冒烟测试
* 接受实盘测试必须以极小仓位、明确留存验证证据并依赖人工确认的方式推进

如果目前仍处于打磨执行逻辑、熟悉命令行操作或验证模拟盘失败场景的阶段，请暂缓引入实盘凭证。

## 2. 实盘凭证的配置方式

实盘凭证只能配置在当前终端环境中，或存放在代码仓库外部的私有文件内。代码仓库根目录下的以下文件严禁用于存放实盘凭证：

* `.env`
* `.env.local`
* `.envrc`
* `.envrc.local`

当前命令行工具会将代码仓库根目录中出现的长桥实盘凭证视为危险配置，并在执行实盘下单指令时强制拦截。

推荐的配置方式分为以下两种：

### 推荐方式一：在当前终端环境中临时导出

```bash
export LONGPORT_APP_KEY=...
export LONGPORT_APP_SECRET=...
export LONGPORT_ACCESS_TOKEN=...
export LONGPORT_REGION=cn
export LONGPORT_ENABLE_OVERNIGHT=true
export QEXEC_ENABLE_LIVE=1
```

### 推荐方式二：从代码仓库外部的私有文件加载

建议在代码仓库外部创建一个私有配置文件，例如建立 `~/.config/qexec/longport-live.env` 文件并写入以下内容：

```bash
export LONGPORT_APP_KEY=...
export LONGPORT_APP_SECRET=...
export LONGPORT_ACCESS_TOKEN=...
export LONGPORT_REGION=cn
export LONGPORT_ENABLE_OVERNIGHT=true
export QEXEC_ENABLE_LIVE=1
```

随后在当前终端中执行加载命令：

```bash
source ~/.config/qexec/longport-live.env
```

如果你希望新建的终端会话能够自动加载这些变量，可以将以下指令追加到 `~/.bashrc` 或 `~/.bash_profile` 文件中：

```bash
[ -f "$HOME/.config/qexec/longport-live.env" ] && source "$HOME/.config/qexec/longport-live.env"
```

采用此方式的优势在于：
* 交互式终端或登录类型的终端会自动加载相关配置
* 实盘凭证绝对不会落入代码仓库的本地文件中

## 3. 执行前就绪性检查

首先，请再次确认代码仓库根目录的相关配置文件中不存在实盘凭证。模拟盘的凭证（如 `LONGPORT_ACCESS_TOKEN_TEST`）允许保留在本地文件中，但实盘凭证必须隔离。

确认无误后，请先运行只读状态的就绪性检查：

```bash
uv run python -m quant_execution_engine config --broker longport
uv run python -m quant_execution_engine preflight --broker longport
uv run python -m quant_execution_engine account --broker longport
uv run python -m quant_execution_engine quote AAPL --broker longport
```

配置查询命令（config）目前会直接打印出各项核心参数的加载来源。请通过终端的输出信息，仔细确认实盘路径是否正确读取了外部的私有配置文件。

只有当上述只读检查全部顺利通过后，才能附带执行参数进入实盘下单环节。

## 4. 最小化目标持仓文件

请准备一个用于冒烟测试的目标持仓文件。要求标的具有足够高的流动性，且仓位极小、在你的绝对风险可承受范围内。示例如下：

```json
{
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

请将上述内容保存至以下路径：

```bash
outputs/targets/real-smoke-aapl.json
```

## 5. 最小化实盘操作流程

### 5.1 生成调仓预览（干跑模式）

```bash
uv run python -m quant_execution_engine rebalance outputs/targets/real-smoke-aapl.json --broker longport
```

在此阶段需确认：
* 输入文件被正确解析
* 标的代码和市场后缀正确无误
* 价格和数量的变化差异符合预期
* 风控拦截门禁未出现异常阻断

### 5.2 执行实盘下单

```bash
uv run python -m quant_execution_engine rebalance outputs/targets/real-smoke-aapl.json --broker longport --execute
```

### 5.3 立即查询状态

下单后请立即执行订单查询与状态对账：

```bash
uv run python -m quant_execution_engine orders --broker longport --symbol AAPL
uv run python -m quant_execution_engine reconcile --broker longport
```

若本地执行状态中已成功获取券商返回的订单编号，可进一步查询该单笔订单的生命周期详情：

```bash
uv run python -m quant_execution_engine order <broker-order-id> --broker longport
```

## 6. 如何验证撤单逻辑

当前实盘调仓主路径默认生成的是市价单。这意味着订单可能会被券商迅速撮合成交，从而证明订单提交、查询和对账环节正常运作，但你未必有机会顺手验证撤单操作。

如果在你查询时该订单仍处于未成交的开启状态，请执行以下命令验证撤单：

```bash
uv run python -m quant_execution_engine cancel <broker-order-id> --broker longport
uv run python -m quant_execution_engine reconcile --broker longport
```

如果订单在提交后瞬间成交完毕：
* 本次测试将仅覆盖提交、查询、对账以及成交恢复环节的验证
* 撤单的验证证据可以留待后续遇到更适合挂单的测试场景时再行补齐

当前项目的范畴暂不涉及扩展更为复杂的限价单或算法订单提交框架。

## 7. 应当留存的测试证据

强烈建议在本次测试完成后留存以下记录：

* 输入的目标持仓文件
* 实盘下单命令的终端输出日志
* 相关查询、对账与撤单命令的终端输出日志
* 对应的结构化审计日志文件（位于 `outputs/orders/` 目录下）
* 对应的本地执行状态文件（位于 `outputs/state/` 目录下）
* 一段人工复查备注（需包含运行时间、标的、券商订单编号、最终状态、是否实际成交以及是否覆盖了撤单环节）

如果你希望将上述验证过程一次性转化为结构化的数据记录，可以直接运行配套的冒烟测试脚手架：

```bash
PYTHONPATH=src python project_tools/smoke_operator_harness.py \
  --broker longport \
  --allow-non-paper \
  --execute \
  --evidence-output outputs/evidence/longport-real-smoke.json \
  --operator-note operator supervised live smoke \
  --operator-note cancel not covered
```

这份自动生成的证据文件将额外保留审计运行编号、状态文件路径、最新跟踪的订单引用以及操作员备注等关键信息。

获取到本次运行的编号后，你可以将所有相关的审计记录、状态文件、目标输入以及测试证据打包为一个本地复查文件包：

```bash
qexec evidence-pack <audit-run-id>
qexec evidence-pack <audit-run-id> --operator-note terminal output reviewed
```

实盘链路是否已从代码连通推进至证据完备，请以成熟度报告（evidence-maturity）中的长桥实盘条目以及本地留存的复查打包文件为准。

## 8. 测试成功判定标准

本次实盘冒烟测试至少需满足以下条件，方可认为针对实盘券商的接入取得了实质性进展：

* 就绪性检查顺利通过
* 实盘执行命令未在本地参数层发生报错
* 券商订单成功进入本地跟踪状态
* 查询或对账命令至少能够成功拉取回一次真实的券商端状态
* 终端输出、审计日志与本地状态文件三者的数据逻辑自洽
* 证据打包命令能够成功生成校验清单，且核心产出文件无缺失

若在此基础上还能进一步获取撤单成功或获取到带迟到成交记录的可解释状态，则本次测试的证据链将更为扎实。

## 9. 模拟盘的定位说明

在本项目中，Alpaca 模拟盘依然具有不可替代的价值，但其角色定位非常明确：

* 它是作为更为稳定、低成本的日常回归测试与冒烟测试的基线环境
* 它在当前代码库中承担着流程跑通验证的兜底作用

也就是说，利用模拟盘来让操作员熟练流转过程、执行自动化测试工装或是验证异常状态的恢复逻辑，是非常合理的。但本项目当前并不会向高度依赖模拟盘的高频算法交易中台方向扩张。

目前阶段最具实际业务价值的工作，依然是优先夯实并补齐长桥实盘链路的最小化验证证据链。