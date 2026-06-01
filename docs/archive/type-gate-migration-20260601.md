# 类型门禁迁移记录：2026-06-01

2026-06-01 完成 Pyright hard gate 迁移。迁移前的 `8 errors, 11 warnings` 中，8 个 optional SDK 动态边界 error 已通过窄化 helper 修复。

迁移完成后的 Pyright 状态为 `0 errors, 11 warnings`：

- `broker/__init__.py` 的 10 个 warning 来自延迟导出列表；兼容导出仍需保留。
- `config.py` 的 1 个 warning 是 PyYAML source 可见性提示，不影响 Pyright hard gate。

任何新增 Pyright error 都会阻塞 hard gate。保留 warning 不能用于绕过执行、风控、状态或 targets contract 缺陷。

mypy 在迁移后的一个发布周期内作为 advisory compatibility 检查保留：

```bash
python ../scripts/run_submodule_checks.py \
  --profile mypy_advisory \
  --submodule quant-execution-engine
```

下一次 release review 只有在 mypy 没有独有阻塞发现且 Pyright warning 分类保持稳定时，才评估移除 advisory。若需要回滚，将顶层 `scripts/submodule_checks.json` 的执行引擎 `type` profile 恢复为 `["uv", "run", "--group", "dev", "mypy", "src"]`；SDK 边界窄化修复继续保留。
