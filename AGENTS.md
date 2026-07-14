# AGENTS.md

本文件说明 `quant-execution-engine` 的协作边界。

## 仓库职责

本仓库只维护交易执行能力：

- `targets.json` 解析和校验
- 执行前检查
- 调仓计划和预演
- 风控和实盘保护
- 券商适配器
- 订单生命周期和本地状态
- 对账、异常恢复和审计证据

策略研究、信号生成、历史回测和原始数据采集由其他仓库维护。

## 环境

```bash
uv sync --group dev --extra cli
```

券商依赖按需安装：

```bash
uv sync --group dev --extra cli --extra longport
uv sync --group dev --extra cli --extra alpaca
uv sync --group dev --extra cli --extra ibkr
```

凭证规则见 `docs/configuration.md`。不要读取、打印或提交 token、密钥、账户信息和真实持仓。

## 测试和质量检查

日常门禁：

```bash
make test
make lint
make format
make typecheck
make quality
```

扩展测试：

```bash
make test-all
make test-integration
make test-e2e
make basedpyright
```

默认 `pytest` 排除 `integration`、`e2e` 和 `slow` 标记。修改券商适配器、订单生命周期或风控逻辑时，应按影响范围补充对应测试。

## 执行安全

- 调仓输入只接受标准 `targets.json`。
- 当前没有默认券商。
- 模拟盘和实盘执行都需要显式选择券商。
- 实盘执行需要保护开关和人工监督。
- 订单状态修改必须经过明确命令。
- 只读查询命令不得产生券商侧变更。
- 异常恢复操作应保留审计记录。
- 部分成交按专用恢复命令处理。
- 不在测试中使用真实账户或实盘凭证。
- 实盘能力成熟度以 `docs/current-capabilities.md` 和受监督证据为准。

## 文档分工

| 内容 | 文档 |
| --- | --- |
| 项目定位和最短路径 | `README.md` |
| 当前支持范围 | `docs/current-capabilities.md` |
| 命令和参数 | `docs/cli.md` |
| 配置、凭证和保护开关 | `docs/configuration.md` |
| `targets.json` | `docs/targets.md` |
| 测试分层 | `docs/testing.md` |
| 架构和订单生命周期 | `docs/architecture.md`、`docs/execution-foundation.md` |
| 券商专项演练 | `docs/*-smoke.md` |
| 历史记录 | `docs/archive/` |

修改公开命令、配置、目标文件契约、券商能力或输出目录时，应同步更新对应文档和行为测试。

## 编辑规则

- 中文说明使用自然、直接的表达和中文标点。
- 保留必要的命令、路径、配置键和 API 名称。
- 用户指南聚焦当前能力和操作步骤。
- 历史迁移记录放入 `docs/archive/`。
- 修改执行逻辑时优先写行为测试。
- 避免依赖源码字符串和文件存在性断言来代替行为验证。
- 不提交 `outputs/`、凭证、本地环境文件和券商数据。

## Git

大范围文档、契约和执行边界调整使用短期分支和 PR。本仓作为工作区子模块时，合并后再更新顶层 gitlink。
