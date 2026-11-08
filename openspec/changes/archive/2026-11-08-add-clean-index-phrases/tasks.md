# Tasks

## 1. 目录数据与匹配测试

- [x] 1.1 在 `app/services/command_matching/catalog.py` 的 `REBUILD_INDEX` 短语组新增 `清理索引`，验证：`uv run python -c "from app.services.command_matching.catalog import COMMAND_CATALOG; print(COMMAND_CATALOG['rebuild_index'])"` 输出中包含该短语
- [x] 1.2 在 `tests/test_command_matching.py` 的子串用例中断言 `清理索引` 与 `帮我清理索引` 命中 `REBUILD_INDEX`，验证：`uv run pytest tests/test_command_matching.py -q` 通过
- [x] 1.3 在 `tests/test_semantic_command_smoke.py` 的 `POSITIVE_SAMPLES` 中新增 `清理索引`、`索引清理`、`清理一下索引`，验证：`uv run pytest -m semantic tests/test_semantic_command_smoke.py -q` 通过（依赖本地 `cache/` 模型）

## 2. 回归与规范校验

- [x] 2.1 运行全量单测 `uv run pytest -q`，确认无回归（重点：`clean` 类负样本与疑问句拦截用例仍通过）
- [x] 2.2 运行 `openspec validate add-clean-index-phrases --strict`，确认增量规范无警告

## Workflow follow-up

- 评审通过后归档本变更。
- 归档后确认 `openspec/specs/semantic-command/spec.md` 已吸收"清理"语义族的覆盖要求。
