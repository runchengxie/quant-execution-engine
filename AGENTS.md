# AGENTS.md

本文件说明 `quant-execution-engine` 的协作边界和本地门禁。

## 仓库职责

本仓库维护：

- `targets.json` 解析和校验
- 执行前检查和调仓预演
- 风控与实盘保护
- 券商适配器和订单生命周期
- 对账、异常恢复和审计证据

策略研究、信号生成、历史回测和原始数据采集由其他仓库维护。

## 框架与适配器边界

- 框架层当前维护通用 `BrokerAdapter` 协议和类型化执行领域对象。
- Alpaca、IBKR、LongPort 与本地预演是当前代码中已有的具体券商后端。
- 当前 `main` 没有 vn.py 适配器、依赖或已注册后端。
- Qlib、LEAN、Backtrader 及其他研究或回测框架不在本仓库范围内。
- 文档不得把通用协议、规划讨论或外部框架能力写成已注册后端。

## 开发流程

- 仓库统一使用 `main`。
- 并行会话使用独立克隆，并在各自的 `main` 上工作。
- 修改前确认工作区状态，保留其他会话已有的改动。
- 先提交本仓库，再由 `research-workspace` 更新对应 gitlink。
- 不提交 `outputs/`、凭证、本地环境文件和券商数据。

## 环境和本地门禁

```bash
uv sync --group dev --extra cli
make quality
```

发布或大范围改动还应运行：

```bash
make basedpyright
make test-all
```

默认 `pytest` 排除 `integration`、`e2e` 和 `slow` 标记。维护性预算由 `make maintainability` 检查。

在 `research-workspace` 托管检出中，`core.hooksPath` 指向 superproject 的共享钩子目录。共享 `pre-push` 会先校验推送引用，再按清单运行仓库检查。单独克隆本仓库时不会继承这套钩子，推送前需手动运行 `make quality`。

## 执行安全

- 调仓输入只接受包含 `targets` 数组的标准 `targets.json`。
- 当前没有默认券商。
- 模拟盘和实盘都需要显式选择券商。
- 实盘需要保护开关和人工监督。
- 只读查询命令不得产生券商侧变更。
- 异常恢复操作应保留审计记录。
- 测试不得使用真实账户或实盘凭证。
- 能力成熟度以 `docs/current-capabilities.md` 和受监督证据为准。
- 框架支持范围以 `docs/architecture.md` 的当前代码边界为准。

凭证规则见 `docs/configuration.md`。不要读取、打印或提交 token、密钥、账户信息和真实持仓。

## 文档和测试

修改公开命令、配置、目标文件契约、券商能力或输出目录时，应同步更新文档和行为测试。

- 项目入口：`README.md`
- 当前支持范围：`docs/current-capabilities.md`
- 命令与配置：`docs/cli.md`、`docs/configuration.md`
- 测试分层：`docs/testing.md`
- 架构与生命周期：`docs/architecture.md`、`docs/execution-foundation.md`
- 券商演练：`docs/*-smoke.md`
- 历史记录：`docs/archive/`

中文说明使用自然、直接的表达和中文标点。保留必要的命令、路径、配置键和 API 名称。历史迁移记录放入 `docs/archive/`。
