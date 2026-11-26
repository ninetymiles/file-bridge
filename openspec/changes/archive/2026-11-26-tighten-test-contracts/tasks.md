# Tasks

## 1. 规格调整

- [x] 1.1 新建 `specs/log-redaction/spec.md`（只含脱敏要求，标注评审核验）并确认 `openspec show tighten-test-contracts --json --deltas-only` 可读到该要求
- [x] 1.2 删除 `runtime-logging` 能力（delta 全部走 REMOVED + Reason/Migration），并在 `photo-review`、`storage-warmup` 提交 MODIFIED delta（去掉日志级别/文本表述）；验证：`openspec validate --strict` 通过
- [x] 1.3 确认 `design.md`「实现约定」八条完整覆盖被下线规格的内容（级别边界、发送先于日志、连接结论、httpx 抑制、脱敏、探测报告、预热日志、接收摘要），不新增文档；验证：逐条比对无遗漏
- [x] 1.4 在 `storage-warmup` delta 新增「唤醒提示的发送路径不含本地 I/O」要求（标注评审保证、无测试）；验证：`openspec validate --strict` 通过且 `openspec show tighten-test-contracts --json --deltas-only` 能读到该要求

## 2. A 类：文本断言改为行为断言

- [x] 2.1 `test_startup_index_rebuild.py`：删日志断言、用例改名；验证：仅保留 `rebuild_index.assert_called_once_with()`
- [x] 2.2 `test_media_review_reply.py`：删 `_wait_for_log` 与全部 `caplog`；两个超时用例改为等待假 reviewer 的取消事件；验证：取消事件发生且 `len(replies) == 1`
- [x] 2.3 `test_command_matching.py`：删 3 条日志断言与 `test_factory_builds_semantic_when_enabled`；验证：`isinstance(matcher, SubstringCommandMatcher)` 与构造失败抛错用例通过
- [x] 2.4 `test_file_downloader.py`：删 INFO/DEBUG 边界用例、失败用例的 error_logs、`Streamed download complete` 断言；验证：URL 返回、抛错、`sha256`/`file_size`/落盘内容断言仍在
- [x] 2.5 `test_photo_review.py`：删 probe 日志断言与 `test_warmup_success_stays_below_info`；失败用例只留“不抛异常”；验证：`probe.ready/status/reachable/models/model_present` 与 `review() is None` 断言仍在
- [x] 2.6 `test_config.py`：非法级别用例改断言 `setup_logger("verbose").level == logging.INFO`；验证：用例不再引用 `caplog`

## 3. B 类：删除过度测试与夹具

- [x] 3.1 `test_pipeline.py`：删回复日志 2 条、接收摘要 4 条、`sends_before_logging`、`warmup_before_first_info_log` 与 `_EventLogHandler`；补一条“发送失败返回 `None`”的行为用例；验证：该文件无 `caplog`
- [x] 3.2 `test_media_file_handler.py`：下载开始日志断言改为 `download_file_stream.await_count == 2`；验证：多图用例通过且不再引用 `caplog`
- [x] 3.3 `test_config.py`：删启动摘要 2 条、连接改写 4 条、`test_repeated_setup_logger_does_not_duplicate_output`，以及 `configured_logs`、`_make_stream_record`、`_emit`；验证：文件内无日志夹具残留
- [x] 3.4 `test_integration.py`：顺序用例删 `log_received` 事件与三个日志辅助函数，保留「唤醒提示 → 探针完成 → 最终回复」；删 httpx 抑制用例；验证：事件序列断言通过
- [x] 3.5 全仓库校验：`grep -rn "caplog\|LogHandler" tests/` 无结果；验证：检查命令输出为空

## 5. 顺序约束的落点（注释与文档，无自动化测试）

- [x] 5.1 `app/handlers/message.py` 的 `PipelineHandler.async_reply_text` docstring：保留现有「先发送后记录」说明，补一句「禁止把本地日志移到发送之前」的显式禁令；验证：docstring 含 `Do NOT move the log call before the send` 禁令句与理由
- [x] 5.2 `app/handlers/message.py` 的 `_dispatch` 内 `on_waking`：补注释说明该回调里的用户可见发送必须先于任何本地日志写入；验证：注释与 `async_reply_text` 的说明一致，不重复整段理由
- [x] 5.3 `app/services/disk_warmup.py` 的 `ensure_storage_ready` docstring：补一句「`on_waking` 必须先完成用户可见发送，再做本地记录」；验证：`grep -n "on_waking" app/services/disk_warmup.py` 附近可读到该约束
- [x] 5.4 `docs/storage.md` 冷盘小节：在「先回复正在唤醒存储服务」之后补一句「本地日志记录在发送完成之后，避免冷盘 I/O 延后提示」；验证：该句可检索到

## 6. 集成校验

- [x] 6.1 运行全量测试；验证：`uv run pytest` 全部通过
- [x] 6.2 对照 design.md 的「叶子契约保留清单」逐项确认仍有叶子用例；验证：清单 7 项均能指出对应测试用例名

## Workflow follow-up

- C 类白盒测试（mock 协作者、私有函数/属性、模块内 patch）单独分析后再开变更。
- 本变更完成后执行 `decouple-callback-ack`，避免同一批测试文件改两遍。
- 执行 `decouple-callback-ack` 前先修订该变更：`design.md` 中“现有规范已要求预热先于任何本地 INFO 日志”的引用失效，`tasks.md` 1.2 的“断言 ERROR 日志”需改为行为判据。
