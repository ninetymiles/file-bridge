# Tasks

## 1. 生产侧接缝（先做，行为不变）

- [x] 1.1 `create_pipeline` 增加可选 `file_downloader` 参数（为 None 时按原逻辑构造）；验证：`uv run pytest tests/test_integration.py` 通过，且 `main()` 调用不传该参数也能启动
- [x] 1.2 `PipelineHandler.__init__` 增加 `warmup_delay: float = 3.0`，`_dispatch` 传给 `ensure_storage_ready`；验证：现有冷盘用例通过，`grep -rn "warmup_delay" app/` 可见默认值与唯一传参点
- [x] 1.3 `app/main.py` 将 `_ReviewGate` / `_build_wake_warmup` 重命名为 `ReviewGate` / `build_wake_warmup` 并同步全部引用；验证：`grep -rn "_ReviewGate\|_build_wake_warmup" app/ tests/` 为空

## 2. 删除零信息量断言

- [x] 2.1 删除 `tests/test_index_report.py::test_snapshot_does_not_access_database` 及 `sqlite3`/`monkeypatch` 相关导入；验证：该文件测试全部通过
- [x] 2.2 删除 `tests/test_command_matching.py` 中 `passage_inputs` / `query_inputs` 两条断言；验证：语义匹配三条用例仍通过且不再引用这两个字段
- [x] 2.3 删除 `tests/test_runner.py` 的 `logger.warning.called` 与三处 `client.stop.assert_not_awaited()`；验证：`test_runner.py` 全部通过且不再出现 `client.stop` 断言
- [x] 2.4 删除 `tests/test_daily_report_scheduler.py` 的 `sleeper.calls == [3600]` 与 `_started_tasks` 反查；验证：启停与触发用例通过，文件内不再引用 `asyncio.all_tasks`
- [x] 2.5 删除 `tests/test_lifecycle_notifier.py` 的身份断言与「第一条是群」假设；验证：通知内容用例全部通过

## 3. 改写为黑盒行为断言

- [x] 3.1 `test_media_file_handler.py`：构造真实 `MetadataStore(tmp_path)`，落盘后读回记录断言 `media_type` / `sender_id` / `sender_staff_id` / `saved_path` / `original_filename`；验证：用例通过，文件内不再有 `async_insert_record.call_args`
- [x] 3.2 `test_media_file_handler.py`：元数据行用例改用真实 EXIF 图片，删除 `patch("app.handlers.message.extract_media_metadata")`；验证：三条元数据用例通过，文件内不再出现该 patch
- [x] 3.3 `test_command_handler.py`：引导回复两条用例改为 `CommandHandler.handle()` 层断言（层级、4 个能力项、前缀有无），删除 `random.choice` patch；验证：用例通过且文件内无 `build_guide_reply` 直接调用
- [x] 3.4 `test_lifecycle_notifier.py`：改为按内容定位 `reply_markdown_card` 调用（包含快照正文 / 包含「服务已就绪」），断言标题与版本一致；验证：两个目标用例通过
- [x] 3.5 `test_integration.py`：用 `FileDownloader(http_client=...)` 注入 `create_pipeline`，删除 `hasattr` 与 `_http_client` 赋值；`ensure_storage_ready` 的 monkeypatch 改为 `warmup_delay=0.05`；`metadata_store` 直接复用局部变量；验证：`grep -rn "_http_client\|ensure_storage_ready" tests/` 无结果
- [x] 3.6 `test_integration.py`：`ReviewGate` / `build_wake_warmup` 用例改用公开名，`monkeypatch.setattr(main_module, "warmup_model", ...)` 保持不变；验证：预热门控用例通过

## 4. 集成校验

- [x] 4.1 运行全量测试；验证：`uv run pytest` 全部通过
- [x] 4.2 白盒残留检查：验证 `grep -rn "\._[a-z]" tests/` 只剩 `self._` 测试替身与 `_make_*` 辅助函数，无被测对象的私有属性访问
- [x] 4.3 叶子覆盖对照：确认 `design.md` 中提到的契约（入库字段、元数据行、引导结构、通知内容、调度启停、信号注册、幂等启动）各自仍有独立用例；验证：逐项指出用例名

## Workflow follow-up

- 本变更完成后再执行 `decouple-callback-ack`；届时 `test_drain` 需要观察派发任务，可复用本变更确立的「只通过公开属性注入」原则。
- 若审查后认为 `warmup_delay` 不该作为构造参数，回退 1.2 并保留原 monkeypatch，其余任务不受影响。
