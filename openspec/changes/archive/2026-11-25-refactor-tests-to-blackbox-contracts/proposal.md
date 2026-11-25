# Proposal: refactor-tests-to-blackbox-contracts

## Why

当前 302 条测试中约 44 条（≈15%）不是面向契约的黑盒测试：它们直接调用 `_merge_rich_text`、`_format_reviews`、`_ReviewBatch`、`_next_daily_check`、`_DingTalkStreamLogFilter` 等私有符号，或断言 `_active_tasks`、`_runner_task`、`_model.init_kwargs` 等内部状态。这类用例把测试绑在实现结构上：产品代码做等价重构时会无意义地失败，而真正对外的行为契约反而可能漏测。

本变更把这些用例收敛到公共入口（`handle` / `process` / `start` / `stop` / `review` / CLI / 日志输出）可观测的行为上，并删除已被同一契约的 handler 级用例完全覆盖的重复测试。测试数量会减少，但契约覆盖不降低。

## What Changes

### P0：删除冗余与修正断言（不改变测试意图）

- 删除 `tests/test_command_handler.py` 中 4 条直接调用 `CommandHandler._merge_rich_text` 的用例；richText 合并/占位符/`@` 剥离行为已由 `handle()` 级用例覆盖。
- 删除 `tests/test_media_review_reply.py` 中 3 条直接调用 `_format_reviews` 的用例；单条/多条/空结果的回复形态已由 `handle()` 级用例覆盖。
- 重写 `tests/test_runner.py::test_request_stop_raises_on_second_signal`：改为真实连续调用两次 `request_stop()`，不再手动写 `_is_shutting_down`。

### P1：把剩余白盒观测改为公共入口观测

- **日志**：`tests/test_config.py` 的 5 条 `_DingTalkStreamLogFilter` 用例改为经 `setup_logger()` 配置后发送日志并断言输出；`tests/test_pipeline.py` 的 4 条 `_log_received_message` 用例改为经 `process()` + 日志捕获；`tests/test_integration.py` 的 2 处私有方法替换改为日志记录顺序断言。
- **调度器**：删除对 `_next_daily_check` / `_scheduler_loop` 的直接调用，改为用可注入的时钟与 sleep 驱动 `start()`，从 `run_daily_check` 是否触发观察 09:00 行为。为此给 `DailyReportScheduler` 增加两个可选构造参数（默认行为不变）。
- **点评批次**：删除 3 条 `_ReviewBatch` 直测；"窗口内合并 / 窗口外补发 / 超时取消 / 首请求锁定截止"全部通过 `PipelineHandler.process()` 观察回复条数与内容。
- **关停**：删除 4 条对 `pipeline._active_tasks` 的断言，保留并强化"任务被取消 / 归档不被中断 / drain 超时放弃"的可观测结果断言。
- **BotService**：把 `_runner_task`、`_is_shutting_down` 断言改为 `client.start` 是否只启动一次、`start_and_wait()` 是否在限时内返回、`client.stop` 是否从未被调用、离线通知是否送达。
- **embedding 缓存**：2 条检查 `embedder._model.init_kwargs` 的用例改为测试公开的 `resolve_model_cache_dir()`；删除 1 条断言 `_phrase_vectors` 维度的模型细节用例。
- **文件名清洗**：删除 `sanitize_sender_id` / `sanitize_extension` 的 2 条内部函数单测；文件名与目录契约已由 `generate_saved_filename` / `save_file` 用例覆盖。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 —— 纯测试重构；唯一的生产改动是 `DailyReportScheduler` 增加默认行为不变的时钟/sleep 注入点，不改变任何对外行为。`.openspec.yaml` 设置 `skip_specs: true`。）

## Impact

- 测试：`tests/test_command_handler.py`、`tests/test_config.py`、`tests/test_daily_report_scheduler.py`、`tests/test_drain.py`、`tests/test_file_storage.py`、`tests/test_integration.py`、`tests/test_media_review_reply.py`、`tests/test_pipeline.py`、`tests/test_runner.py`、`tests/test_semantic_command_smoke.py`、`tests/test_command_matching.py`。
- 生产代码：仅 `app/services/daily_report_scheduler.py`（可选 `clock` / `sleep` 注入，默认 `datetime.now` / `asyncio.sleep`）；不新增公开 API、不改配置、不改消息行为。
- 不涉及依赖、数据迁移或部署方式。
