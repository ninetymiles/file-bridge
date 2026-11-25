# Tasks

## 1. P0：删除重复白盒用例并修正断言

- [x] 1.1 在 `tests/test_command_handler.py` 先补充/参数化 handler 级 richText 用例，覆盖“`@` 在段尾”“纯文本 richText”“私聊无 `@`”三种输入（经 `CommandHandler.handle()` 断言 `matcher.received_texts` 与 `ReplyTier`）；确认原 `test_merge_rich_text_*` 的契约已被覆盖后删除这 4 条直测
- [x] 1.2 删除 `tests/test_media_review_reply.py` 中 3 条 `_format_reviews` 直测；逐一确认单条无编号、多条顺序编号、空结果分别由 `test_review_within_window_merges_into_one_reply`、`test_group_reviews_merge_into_one_labelled_message`、`test_review_failure_keeps_the_existing_single_reply` / `test_group_all_failures_send_no_followup` 覆盖
- [x] 1.3 重写 `tests/test_runner.py::test_request_stop_raises_on_second_signal`：创建 `BotService` 后连续调用两次 `request_stop("SIGINT")`，第一次正常、第二次抛 `KeyboardInterrupt`；删除 `_is_shutting_down` 预置
- [x] 1.4 运行 `uv run pytest tests/test_command_handler.py tests/test_media_review_reply.py tests/test_runner.py -q`，确认 P0 无回归

## 2. P1：日志测试改为公共配置与输出

- [x] 2.1 重写 `tests/test_config.py` 的 5 条 `_DingTalkStreamLogFilter` 用例：挂测试 handler → `setup_logger("DEBUG")` → 通过 `logging.getLogger("file-bridge").handle(record)` 发送 `filename="stream.py"` 的记录 → 断言最终文本/级别；删除 `_DingTalkStreamLogFilter` 的 import
- [x] 2.2 重写 `test_setup_logger_attaches_no_private_handler` 为“重复调用不产生重复输出”：连续两次 `setup_logger()` 后发一条唯一标记日志，用 `capsys` 断言标记只出现一次；重写 `test_setup_logger_sets_httpx_to_warning` 为发出 httpx INFO 与 WARNING 各一条，断言 INFO 不出现、WARNING 出现
- [x] 2.3 重写 `tests/test_pipeline.py` 的 4 条 `_log_received_message` 用例：用 `PipelineHandler([])`，设置 `reply_text = MagicMock()`、`storage_probe = lambda: None`，经 `await pipeline.process(callback)` + `caplog` 断言 INFO 正文与 `downloadCode` 不泄漏
- [x] 2.4 重写 `test_dispatch_runs_storage_warmup_before_first_info_log`：经 `process()` 驱动，用自定义 logging handler 记录日志事件，断言 probe 事件早于第一条 `Received ...` INFO 记录
- [x] 2.5 重写 `tests/test_integration.py` 两处 `_log_received_message` 替换：改为在 `file-bridge` logger 上挂记录 handler，按事件顺序断言“唤醒提示 → probe 完成 → 接收日志 → 最终回复”；probe 失败用例断言没有 `Received` 记录
- [x] 2.6 运行 `uv run pytest tests/test_config.py tests/test_pipeline.py tests/test_integration.py -q`

## 3. P1：调度器改为可注入时间并通过 `start()` 验证

- [x] 3.1 在 `app/services/daily_report_scheduler.py` 的 `DailyReportScheduler.__init__` 增加可选 `clock: Callable[[], datetime] = None` 与 `sleep: Callable[[float], Awaitable[None]] = None`，内部保存 `self._clock = clock or datetime.now`、`self._sleep = sleep or asyncio.sleep`
- [x] 3.2 将 `last_check` 初始化、`run_daily_check()` 的基线更新、`_scheduler_loop()` 的 `now` / `await asyncio.sleep(...)` / 触发比较全部改用 `self._clock()` 与 `self._sleep()`；默认参数保持现有行为，`main()` 不改
- [x] 3.3 重写 `tests/test_daily_report_scheduler.py`：删除 3 条 `_next_daily_check` 与 2 条 `_scheduler_loop` 直测；新增 `FakeClock` / `FakeSleep`，经 `scheduler.start()` 覆盖“09:00 触发”“09:00 前不触发”“start/stop 幂等”
- [x] 3.4 运行 `uv run pytest tests/test_daily_report_scheduler.py -q`，确认 09:00 行为与现有 `run_daily_check` 用例均通过

## 4. P1：点评、关停、runner、embedding 与文件名

- [x] 4.1 删除 `tests/test_media_review_reply.py` 中 3 条 `_ReviewBatch` 直测；新增一条 `process()` 级用例验证“截止从首个请求起算，不被后续下载推迟”（第一张点评阻塞、第二张下载延迟、总时限取小值，断言最终只有 1 条回复且出现取消 WARNING）
- [x] 4.2 将 `tests/test_media_review_reply.py` 的 `_wait_for_reviews` 改为基于回复事件/假点评器完成事件的等待，不再读取 `handler._review_tasks`；删除 `test_disabled_review_keeps_single_reply` 中的 `_review_tasks == set()` 断言
- [x] 4.3 清理 `tests/test_drain.py`：删除 `test_task_registers_for_drain_and_deregisters_on_finish`，其余 3 条删除 `pipeline._active_tasks` 断言，保留“未调用 handler / 取消回复 / 归档完成 / 超时放弃”等结果断言
- [x] 4.4 重写 `tests/test_runner.py` 的私有 task 断言：`test_service_lifecycle_and_graceful_shutdown`、`test_service_without_notifier`、`test_shutdown_cancels_runner_task_without_client_stop`、`test_shutdown_completes_when_offline_notify_throws`、`test_start_is_idempotent` 改为断言 `client.start` 调用次数、`start_and_wait()` 限时返回、`client.stop` 未被调用、离线通知送达、mock start 的取消标志
- [x] 4.5 重写 `tests/test_command_matching.py` 两条缓存目录用例，改为断言公开 `resolve_model_cache_dir()` 的默认值与 `FASTEMBED_CACHE_PATH` 覆盖；删除 `tests/test_semantic_command_smoke.py::test_embedding_dimension`
- [x] 4.6 删除 `tests/test_file_storage.py` 的 `test_sanitize_sender_id` 与 `test_sanitize_extension`，确认 `generate_saved_filename` / `save_file` 用例仍覆盖路径穿越、默认扩展名与截断行为
- [x] 4.7 运行 `uv run pytest tests/test_media_review_reply.py tests/test_drain.py tests/test_runner.py tests/test_command_matching.py tests/test_file_storage.py -q`

## 5. 验证与收口

- [x] 5.1 静态检查测试目录不再引用白盒符号：`grep -rnE "_merge_rich_text|_format_reviews|_ReviewBatch|_next_daily_check|_scheduler_loop|_DingTalkStreamLogFilter|_active_tasks|_runner_task|_is_shutting_down|_model\.init_kwargs|_phrase_vectors" tests/` 无输出（测试替身自身的 `self._x` 除外）
- [x] 5.2 运行 `uv run pytest` 全绿，记录重构前后的测试条数与通过数
- [x] 5.3 运行 `uv run pytest -m semantic`，确认语义冒烟不受调度器/缓存测试改写影响
- [x] 5.4 运行 `openspec validate refactor-tests-to-blackbox-contracts --strict`
