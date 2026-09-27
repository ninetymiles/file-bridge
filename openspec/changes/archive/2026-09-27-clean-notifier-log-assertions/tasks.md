## 1. 测试断言清理

- [x] 1.1 `tests/test_lifecycle_notifier.py`：移除 5 处诊断日志断言——静默跳过用例的 `logger.debug.assert_called()`、异常隔离用例/异常不崩溃用例/超时用例的 `logger.warning.assert_called()`、空卡片实例用例中的 WARNING 文本匹配及其 `warning_texts` 拼接代码；断言只保留返回值（`True`/`False`）与发送交互（如异常隔离用例的 `call_count == 2`）；同步删除仅为日志断言存在的 `logger = MagicMock()` 及构造参数；运行 `uv run pytest tests/test_lifecycle_notifier.py -q` 验证全部通过

- [x] 1.2 运行 `uv run pytest -q` 全量测试通过，确认清理未影响其它用例

## 2. 校验与归档顺序

- [x] 2.1 运行 `openspec validate clean-notifier-log-assertions --strict` 确认工件合法
- [x] 2.2 归档顺序检查：确认 `dual-notify-targets-and-staff-id` 先于本变更 archive（两个变更 MODIFIED 同一需求，倒序归档会造成需求内容覆盖错误）
