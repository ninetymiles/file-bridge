
## 1. 移除加法 handler

- [x] 1.1 从 `app/handlers/message.py` 删除 `CalcBotFallbackHandler` 类定义；从 `app/handlers/__init__.py` 移除其 import 与 `__all__` 条目；验证 `python -c "import app.handlers"` 不报错且 `grep -rn CalcBotFallbackHandler app/` 无残留
- [x] 1.2 从 `app/main.py` 移除 `CalcBotFallbackHandler` import 与 `create_pipeline()` 中的装配行；验证 `python -c "import app.main"` 不报错

## 2. task 链 + handler 自治取消

- [x] 2.1 在 `app/handlers/message.py` 的 `BaseMessageHandler` 新增 `cancel_tasks() -> None` 默认 no-op 方法；验证 `python -c "import app.handlers"` 不报错
- [x] 2.2 重构 `MediaFileHandler`：新增 `self._interruptible_tasks: set[asyncio.Task]`；将下载阶段包成 `asyncio.create_task(self._download_phase(...))` 子 task 并 `add` 进 set，`await` 之，`finally` 中 `discard`；`except asyncio.CancelledError` 内回复"服务正在关闭，下载任务已取消"并 `return True`；归档阶段（去重、保存、入库、回复）保持内联执行；实现 `cancel_tasks()` 遍历 `list(self._interruptible_tasks)` 调用 `task.cancel()`；验证 `uv run pytest tests/test_media_file_handler.py` 全部通过
- [x] 2.3 重构 `PipelineHandler` 排水（内联，不抽类）：`_active_tasks` 改为 `set[asyncio.Task]`（移除 Event）；`begin_drain()` 置 `_draining=True` 并遍历所有 handler 调 `cancel_tasks()`；`drain_active_tasks(timeout)` 改为纯 `asyncio.wait(self._active_tasks, timeout=timeout)`（删除选择性 cancel 循环）；删除 `mark_download_done` 方法，`process()` 入口仍检查 `is_draining()` 并调用 `register/unregister_current_task`；验证 `uv run pytest tests/test_drain.py` 全部通过
- [x] 2.4 确认 `app/core/runner.py` 的 `stop()` 调用面不变（仍调用 `pipeline.begin_drain()` 与 `pipeline.drain_active_tasks()`）；验证 `uv run pytest tests/test_runner.py` 全部通过

## 3. 移除 add_handler

- [x] 3.1 从 `app/handlers/message.py` 删除 `PipelineHandler.add_handler` 方法；验证 `grep -rn add_handler app/ tests/` 无残留且 `uv run pytest` 全量通过

## 4. 测试清理

- [x] 4.1 从 `tests/test_integration.py` 移除加法测试步骤（第 5 步 `10 + 25`）及对应断言；验证 `uv run pytest tests/test_integration.py` 通过
- [x] 4.2 从 `tests/test_pipeline.py` 移除断言日志正文的 5 个用例（`test_debug_logs_headers_and_full_raw_data`、`test_private_text_info_summary_no_body_debug_has_content`、`test_group_richtext_info_metadata_only_debug_has_segments`、`test_picture_info_has_no_code_debug_has_full_code`、`test_file_info_summary_includes_filename`）；保留 `test_pipeline_execution_order` 与 `test_async_reply_text`；验证 `uv run pytest tests/test_pipeline.py` 通过

## 5. observability spec 改写

- [x] 5.1 将 `openspec/specs/observability/spec.md` 改写：删除两个 Requirement（回调消息诊断日志、媒体下载链路诊断日志）及其全部 Scenario，仅保留 Purpose 段说明"日志为实现内部排障手段，非系统契约"；验证 `openspec validate cleanup-handler-pipeline --strict` 通过

## 6. 整体验证

- [x] 6.1 运行 `uv run pytest` 全量通过；运行 `python -c "import app.main"` 冒烟通过；运行 `openspec validate cleanup-handler-pipeline --strict` 通过
