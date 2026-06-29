# 类型门禁迁移记录：2026-06-01

2026-06-01 完成第一轮类型门禁迁移。迁移前的 `8 errors, 11 warnings` 中，8 个 optional SDK 动态边界 error 已通过窄化 helper 修复。

当前统一口径为 `ty check` 阻塞门禁、BasedPyright 建议项、mypy 单独观察项。迁移完成后的 BasedPyright 状态为 `0 errors, 11 warnings`：

- `broker/__init__.py` 的 10 个 warning 来自延迟导出列表；兼容导出仍需保留。
- `config.py` 的 1 个 warning 是 PyYAML source 可见性提示，不影响阻塞类型门禁。

任何新增 `ty check` error 都会阻塞类型门禁。BasedPyright warning 不能用于绕过执行、风控、状态或 targets contract 缺陷。

mypy 在迁移后的一个发布周期内作为建议兼容检查保留：

```bash
python ../scripts/run_submodule_checks.py \
  --profile mypy_advisory \
  --submodule quant-execution-engine
```

下一次发布复核中，如果 mypy 没有独有阻塞发现，且 BasedPyright warning 分类保持稳定，可以评估移除 mypy 建议项。SDK 边界窄化修复继续保留。
