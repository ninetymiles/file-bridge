# Design: refactor-tests-to-blackbox-contracts

## Context

见 `proposal.md` 的 Why。当前测试把观测点放在实现内部：直接调用 `_merge_rich_text` / `_format_reviews` / `_ReviewBatch` / `_next_daily_check` / `_scheduler_loop` / `_DingTalkStreamLogFilter`，或断言 `_active_tasks` / `_runner_task` / `_is_shutting_down` / `_model.init_kwargs` / `_phrase_vectors`。这些符号是产品代码的私有实现，等价重构即可让测试失败。

可用的公共观测面已经足够：

- `MediaFileHandler.handle()` 与 `PipelineHandler.process()`：回复文本、回复条数、日志记录。
- `setup_logger()`：真实的 logging 配置结果与输出。
- `BotService.start()` / `start_and_wait()` / `stop()` / `request_stop()`：协作者调用、返回时机。
- `DailyReportScheduler.start()` / `stop()` / `run_daily_check()`：日报发送与时间基线的可观测结果。
- `FastEmbedEmbedder` 所在模块的公开函数 `resolve_model_cache_dir()`。
- `extract_media_metadata()`、`generate_saved_filename()`、`save_file()` 等模块公共接口。

项目测试约束不变：默认集不读写真环境变量、不连外网、不依赖真实长延时；语义冒烟仍由 `-m semantic` 单独运行。

## Goals / Non-Goals

**Goals:**

- 所有保留的用例都通过公共入口观察行为，不 import 下划线符号，不断言私有属性。
- 删除已被同一契约的 handler 级用例覆盖的重复测试，测试数量下降但契约覆盖不降。
- 唯一的生产改动是给调度器增加默认行为不变的时钟/sleep 注入点，使 09:00 行为可确定性验证。
- 默认测试集保持全绿，且每个被删除的用例都有明确的替代观测路径。

**Non-Goals:**

- 不改变任何消息回复、日志结论、调度时刻、文件名、缓存目录等对外行为。
- 不为了测试新增业务 API；不把 `_merge_rich_text` 之类的辅助函数改名为“公开”来规避问题。
- 不改写已经面向公共入口的用例（handler、集成、CLI、存储、通知、照片点评主链路）。
- 不动两类“公共函数 + 契约输出”的用例：`test_build_guide_reply_*`（只 patch `random.choice` 以稳定输出）与 `tests/test_media_metadata.py` 的相机兼容回归（走公开 `extract_photo_metadata`）。

## Decisions

### D1. P0 删除与合并：先补契约缺口，再删辅助函数单测

| 文件 | 处理 |
|---|---|
| `tests/test_command_handler.py` | 删除 4 条 `_merge_rich_text` 直测。删除前把“`@` 在段尾”“纯文本 richText”“私聊无 `@`”三个输入并入 handler 级参数化用例，保留原有 `handle()` 断言；`@` 在段首与图片占位符已由现有两条 richText 用例覆盖 |
| `tests/test_media_review_reply.py` | 删除 3 条 `_format_reviews` 直测。单条无编号由 `test_review_within_window_merges_into_one_reply` 覆盖；多条顺序与编号由 `test_group_reviews_merge_into_one_labelled_message` 覆盖；空结果由 `test_review_failure_*` 与 `test_group_all_failures_send_no_followup` 覆盖 |
| `tests/test_runner.py` | `test_request_stop_raises_on_second_signal` 改为连续两次调用 `request_stop("SIGINT")`：第一次不抛，第二次抛 `KeyboardInterrupt`，不再预置 `_is_shutting_down` |

`_merge_rich_text` 的“段尾 `@`”目前没有 handler 级覆盖，直接删除会留下缺口，因此 P0 包含一条新增/参数化用例；其余两个输入已有等价覆盖，只做合并。

### D2. 日志测试改为“配置后的真实输出”

`tests/test_config.py` 的 5 条过滤器用例统一改为：

1. 在 root logger 上挂一个测试用 `StreamHandler` 或捕获 handler；
2. 调用公开的 `setup_logger("DEBUG")`，让它把 `_DingTalkStreamLogFilter` 挂到已存在的 root handler 上；
3. 构造 `LogRecord(name="file-bridge", filename="stream.py", ...)` 并通过 `logging.getLogger("file-bridge").handle(record)` 发送；
4. 断言捕获到的最终文本或级别。

这样断言的是“`setup_logger` 配置后日志长什么样”，而不是“过滤器类如何改写 record”。`test_setup_logger_attaches_no_private_handler` 改为：调用两次 `setup_logger()` 后发一条带唯一标记的日志，用 `capsys` 统计标记出现次数必须为 1，验证“不产生重复输出”。`test_setup_logger_sets_httpx_to_warning` 改为：发 httpx INFO/WARNING 各一条，断言 INFO 不出现、WARNING 出现。

`tests/test_pipeline.py` 的 4 条 `_log_received_message` 用例改为 `await PipelineHandler([]).process(callback)`，配 `reply_text = MagicMock()`（避免真实发送）与 `storage_probe = lambda: None`（避免磁盘检查），从 `caplog` 的 INFO 记录断言正文与 `downloadCode` 不泄漏。`test_dispatch_runs_storage_warmup_before_first_info_log` 改为 `process()` + 自定义 logging handler 记录顺序：probe 事件必须早于第一条 `Received ...` 记录。

`tests/test_integration.py` 的两处 `_log_received_message` 替换改为在 `file-bridge` logger 上挂记录 handler；原“reply → probe_done → log_received → final reply”顺序从事件列表 + 日志记录合并后断言，probe 失败用例断言没有 `Received` 记录。

### D3. 调度器：注入时钟与 sleep，测试通过 `start()` 驱动

`DailyReportScheduler.__init__` 增加两个仅关键字可选参数：

```python
clock: Optional[Callable[[], datetime]] = None,
sleep: Optional[Callable[[float], Awaitable[None]]] = None,
```

内部保存 `self._clock = clock or datetime.now`、`self._sleep = sleep or asyncio.sleep`，并在三处替换直接调用：

- `__init__` 的 `last_check = last_check or self._clock()`
- `run_daily_check()` 末尾更新 `self.last_check = self._clock()`
- `_scheduler_loop()` 的 `now = self._clock()`、`await self._sleep(sleep_seconds)`、触发比较 `self._clock() >= next_run`

默认参数保持 `datetime.now` / `asyncio.sleep` 的现有行为，`main()` 无需改动。

测试改用 `FakeClock`（可推进的 `now`）与 `FakeSleep`（按请求秒数推进时钟并 `await asyncio.sleep(0)`，或在测试要求时阻塞）驱动公开的 `start()`：

- “09:00 触发”：起点 08:59，`start()` 后等待 notifier 收到日报，随后 `stop()`；断言 `run_daily_check` 的公开结果（`async_rebuild_index` / `send_to_staff` 各一次）。
- “09:00 前不触发”：起点 08:00，第一次 sleep 即阻塞，断言 notifier 未调用后 `stop()`。
- “start/stop 幂等”：连续 `start()` 两次，用 FakeSleep 的调用次数证明只有一个循环；连续 `stop()` 两次不抛异常。

`_next_daily_check` 与 `_scheduler_loop` 不再被测试直接调用；其行为由上述公共驱动覆盖。备选“把 `_next_daily_check` 改名为公开函数”被否决：那只是换名字，测试仍绑在辅助函数上。

### D4. 点评批次：全部通过 `process()` 观察

删除 3 条 `_ReviewBatch` 直测，保留并补强 handler 级用例：

- 窗口内合并、窗口外补发、总超时取消：沿用现有用例。
- “60 秒截止从首个请求起算，不随后续下载推迟”：新增一条 `process()` 级用例——第 1 张下载后点评立即阻塞，第 2 张下载延迟返回，总时限取小值；断言最终只有 1 条回复且出现取消 WARNING。时间参数取 0.01–0.1 秒量级，与现有用例一致。
- 测试同步：`_wait_for_reviews` 不再读取 `handler._review_tasks`，改为在 `fake_reply_text` 中设置 `asyncio.Event`，按“期望回复条数”等待；需要确认“没有第二条”的用例先等待假点评器的完成事件，再让出事件循环，避免依赖私有队列。
- `test_disabled_review_keeps_single_reply` 删除 `_review_tasks == set()` 断言，只保留“回复仍为一条、点评器未被调用”。

### D5. 关停：删除 `_active_tasks` 断言，保留可观测结果

`tests/test_drain.py`：

- `test_gate_rejects_processing_after_begin_drain`：保留“handler 未被调用 + 返回 OK”，删除 `_active_tasks == set()`。
- `test_task_registers_for_drain_and_deregisters_on_finish`：删除。任务注册是 `process()` 的实现细节，取消与收尾行为已由后两条用例覆盖。
- `test_begin_drain_cancels_interruptible_download_via_handler`、`test_drain_waits_for_non_interruptible_archive_to_finish`：保留“取消回复 / 归档完成 / 任务未被 cancel”，删除 `_active_tasks` 断言。
- `test_drain_on_empty_registry_returns_instantly`、`test_download_cancel_midstream_cleans_temp_file`、`test_drain_timeout_abandons_stuck_task` 已经是公共行为，保留。

不新增生产代码。

### D6. BotService：用协作者调用与完成时机替代私有 task 状态

- 生命周期用例：用 `asyncio.Event` 等待 `client.start` 已进入，再 `request_stop`；断言 `send_offline_notification` 被 await、`client.stop` 未被 await。
- `test_shutdown_cancels_runner_task_without_client_stop`：`mock_start` 捕获 `CancelledError` 并设置 `cancelled` 事件；断言 `start_and_wait()` 在限时内返回、`cancelled` 已置位、`client.stop` 未被调用。
- `test_start_is_idempotent`：断言 `client.start` 只 await 一次、上线通知只发一次，删除 `_runner_task is first`。
- `test_shutdown_completes_when_offline_notify_throws`、`test_service_without_notifier`：保留可观测断言，删除 `_runner_task.done()`。
- `test_request_stop_raises_on_second_signal` 见 D1。

### D7. embedding 缓存与维度

- 2 条 `embedder._model.init_kwargs` 用例改为测试公开的 `resolve_model_cache_dir()`：未设置/空 `FASTEMBED_CACHE_PATH` 时返回工程根 `cache/`，显式设置时返回自定义路径。该函数正是规范“缓存目录默认固定、环境变量覆盖”的公共边界，构造函数已经复用它。
- 删除 `test_embedding_dimension`。512 维是模型属性，不是应用契约；`test_positive_samples_match` / `test_negative_samples_do_not_match` 已从 `match()` 行为覆盖模型可用性。

### D8. 文件名清洗

删除 `test_sanitize_sender_id` 与 `test_sanitize_extension`。`generate_saved_filename` 的既有用例已经覆盖 `../../evil`、`../../etc/passwd`、缺失扩展名、末 4 位截断等最终文件名行为；`save_file` 覆盖目录结构与碰撞。内部清洗函数不再单独测试。

## Risks / Trade-offs

- [`@` 在段尾的覆盖丢失] → P0 先补 handler 级参数化用例再删旧用例；任务中显式要求运行该用例。
- [日志测试依赖 root handler 的全局状态] → 测试内使用唯一标记、`try/finally` 移除自建 handler；不跳过 `setup_logger`，保证验证的是真实配置。
- [`setup_logger` 重复调用累积过滤器] → 过滤器对已改写的消息幂等；重复调用本身就是“无重复输出”用例的一部分。
- [调度器注入参数改变构造签名] → 参数可选且默认值保持原行为；全仓库仅 `main()` 一处生产构造，不需要修改。
- [点评超时用例依赖小延时] → 窗口与时限取 0.01–0.1 秒，只断言“回复条数 / 是否取消”这类离散结果，不断言具体耗时；沿用现有测试的时序尺度。
- [删除测试被视为降低覆盖率] → 每条删除都映射到现有或新增的 handler/服务级用例；任务中列出替代路径，完成后跑全量确认 0 failed。

## Migration Plan

1. 先落 P0（删冗余 + 补 `@` 段尾用例），跑全量确认无回归。
2. 再落 P1：生产侧只改 `DailyReportScheduler` 构造参数；测试按 D2–D8 逐文件改写。
3. 每批结束运行 `uv run pytest`，最后运行 `uv run pytest -m semantic` 确认语义冒烟不受影响。
4. 回滚策略：纯测试 + 默认参数改动，按文件 `git checkout` 即可；无数据/部署迁移。

## Open Questions

（无）
