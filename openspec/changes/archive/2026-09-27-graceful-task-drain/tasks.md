## 1. 在途任务追踪与门控

- [x] 1.1 在 `lib/handlers.py` 的 `PipelineHandler` 中新增：`_draining` 标志、`_active_tasks: set`（含每任务的 `download_done: asyncio.Event` 状态）、`begin_drain()`、`mark_download_done()`、`drain_active_tasks(timeout=10)`（纯同步取消循环：快照内未标记者 `task.cancel()`；随后 `asyncio.wait` 有界等待）；`process()` 入口先查 gate（命中直接 `return AckMessage.STATUS_OK, "OK"`），否则以 `asyncio.current_task()` 注册并 `finally` 注销，运行 `uv run pytest` 确认存量测试全绿

## 2. 阶段检查点与取消回复

- [x] 2.1 修改 `lib/handlers.py` 的 `MediaFileHandler.handle`：调用 `download_file_stream` 前查 `pipeline` drain 标志（命中静默 `return True`）；下载返回后立即调 `pipeline.mark_download_done()`；用 `except asyncio.CancelledError` 包住下载段——回复"任务已取消/中断"后 `raise`；下载返回到标记之间不插入任何 await；运行 `uv run pytest tests/test_pipeline.py` 确认存量用例全绿（注：`test_media_file_handler.py` 的 `MagicMock(spec=PipelineHandler)` 需补 `is_draining.return_value = False`，属新依赖的 mock 配置）
- [x] 2.2 将 `lib/file_downloader.py` 的 `download_file_stream` 清理分支 `except Exception` 改为 `except BaseException`，使任务被取消时 `.tmp` 临时文件同样被清理；运行 `uv run pytest tests/test_file_downloader.py` 确认全绿
- [x] 2.3 新增单测（新建 `tests/test_drain.py`，7 个用例全绿）：a) gate 拒绝且不注册；b) 注册/注销对称；c) 未标记任务被 drain 取消且 task.cancelled()；d) 已标记任务 drain 窗口内完整执行；e) 空集合瞬时返回；f) 下载中取消 → .tmp 清理（httpx.MockTransport 慢流）；g) 超时放弃滞留任务并记 INFO 日志（注：Python 3.14 上 cancel 卡在 to_thread 的任务会立即终结，线程滞留场景改用"吞掉首次取消"的 StubbornHandler 构造）

## 3. 停机序列接入

- [x] 3.1 修改 `lib/runner.py`：`BotService.__init__` 增加 `pipeline` 参数；`stop()` 在取消 runner 任务之前插入两步（`pipeline.begin_drain()` → `await pipeline.drain_active_tasks(timeout=10)`），docstring 同步重排步骤；`app/main.py` 的 `BotService(...)` 调用传参，运行 `uv run pytest` 全量回归通过（49 passed）
- [x] 3.2 Live 冒烟验证：`uv run python -m app.main` 启动连接成功后空闲状态发 SIGINT，确认停机总耗时与现状一致（drain 瞬时）、exit 0、日志含 drain 完成陈述；人工场景验证（需从钉钉端配合发文件）：发送一个大文件后立即 Ctrl-C，确认收到"任务已取消/中断"回复、`output/.tmp/` 无残留、exit 0；发送小文件待回复"保存成功"后再 Ctrl-C，确认 drain 不改变其结果、exit 0（空闲停机已自动验证：SIGINT 1.42s / SIGTERM 均 exit 0、gate 日志就位、无 Task destroyed 噪音；人工发文件两场景由用户在钉钉端确认完成）

## 4. 规范与回归

- [x] 4.1 确认 `specs/lifecycle-management/spec.md` 为纯 ADDED 需求（不与 fix-filename-and-shutdown 的 MODIFIED 块冲突），运行 `openspec validate graceful-task-drain` 通过
- [x] 4.2 运行 `uv run pytest` 全量回归通过（49 passed），全局检索确认无 `task.cancel()` 散落在 drain 机制之外（仅 drain 编排器与既有 runner task 取消两处）
