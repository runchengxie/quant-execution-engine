# AGENTS.md

本文件说明 `quant-execution-engine` 的协作边界。

## 仓库职责

本仓库维护：

- `targets.json` 解析和校验
- 执行前检查和调仓预演
- 风控与实盘保护
- 券商适配器和订单生命周期
- 对账、异常恢复和审计证据

策略研究、信号生成、历史回测和原始数据采集由其他仓库维护。

## 环境和测试

```bash
uv sync --group dev --extra cli
make test
make lint
make format
make typecheck
make quality
```

扩展测试和诊断：

```bash
make test-all
make test-integration
make test-e2e
make basedpyright
```

默认 `pytest` 排除 `integration`、`e2e` 和 `slow` 标记。

## 执行安全

- 输入只接受标准 `targets.json`。
- 当前没有默认券商。
- 模拟盘和实盘都需要显式选择券商。
- 实盘需要保护开关和人工监督。
- 只读查询命令不得产生券商侧变更。
- 异常恢复操作应保留审计记录。
- 测试不得使用真实账户或实盘凭证。
- 能力成熟度以 `docs/current-capabilities.md` 和受监督证据为准。

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

## 编辑规则

- 中文说明使用自然、直接的表达和中文标点。
- 保留必要的命令、路径、配置键和 API 名称。
- 历史迁移记录放入 `docs/archive/`。
- 修改执行逻辑时优先写行为测试。
- 不提交 `outputs/`、凭证、本地环境文件和券商数据。

大范围调整使用短期分支和 PR。合并后再按需更新顶层 gitlink。
