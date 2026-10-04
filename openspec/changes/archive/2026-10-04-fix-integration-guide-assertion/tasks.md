# Tasks

## 1. 修正断言

- [x] 1.1 修改 `tests/test_integration.py` 第 6 步（未命中引导）断言：删除对随机措辞字面词 `"保存"` 的依赖，保留结构契约 `replies[4][0].count("• ") == 4`（恰好一条引导、四项能力条目），`len(replies) == 5` 不变；不改动生产代码与其余步骤

## 2. 验证

- [x] 2.1 单独运行该 integration 测试通过，并多次（≥5 次）运行默认集 `uv run pytest -m general` 确认该用例不再因 RNG 播种状态偶发失败
- [x] 2.2 `openspec validate fix-integration-guide-assertion --strict`
