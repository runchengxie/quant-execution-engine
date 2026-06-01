# 文档首页

这里是 `quant-execution-engine` 的文档入口。根目录 `README.md` 只保留项目定位和最短路径；命令、配置、券商能力、测试和专项演练细节都放在本目录。

## 先按问题找页面

| 我现在的问题 | 先看哪一页 |
| --- | --- |
| 我想确认这个引擎现在支持哪些券商和能力 | `current-capabilities.md` |
| 我想查 `qexec` 有哪些命令和参数 | `cli.md` |
| 我想配置券商凭证、风控阈值或本地 YAML | `configuration.md` |
| 我想知道 `targets.json` 应该长什么样 | `targets.md` |
| 我想跑测试或理解测试分层 | `testing.md` |
| 我想理解架构和核心执行链路 | `architecture.md`、`execution-foundation.md` |
| 我想做 Alpaca 模拟盘冒烟演练 | `alpaca-paper-smoke.md` |
| 我想做盈透模拟盘冒烟演练 | `ibkr-paper-smoke.md` |
| 我想复现长桥模拟盘失败场景 | `longport-paper-failure-smoke.md` |
| 我想谨慎验证长桥实盘路径 | `longport-real-smoke.md` |
| 我想看历史开发清单或迁移记录 | `archive/README.md` |

## 推荐阅读路径

1. 第一次进入仓库：`README.md` -> `current-capabilities.md` -> `configuration.md` -> `cli.md`
1. 准备接入研究输出：`targets.md` -> `cli.md` 的 `rebalance` 部分 -> `current-capabilities.md`
1. 准备跑模拟盘：对应券商的 smoke 文档 -> `testing.md`
1. 准备碰实盘：`current-capabilities.md` -> `configuration.md` -> `longport-real-smoke.md`
1. 维护代码或排查问题：`architecture.md` -> `execution-foundation.md` -> `testing.md`

## 页面分工

- `current-capabilities.md`：券商支持矩阵、能力成熟度、凭证规则和已知限制。
- `cli.md`：`qexec` 命令、参数和操作语义。
- `configuration.md`：环境变量、本地配置文件、实盘保护和配置加载顺序。
- `targets.md`：执行输入文件格式。
- `testing.md`：默认测试、pytest 标记、集成测试、端到端测试和人工监督冒烟测试。
- `architecture.md`：包结构、模块边界和责任分层。
- `execution-foundation.md`：订单生命周期、本地状态、对账、风控和恢复链路。
- `*-smoke.md`：具体券商的专项演练步骤。
- `archive/`：已完成阶段清单和历史迁移记录。
