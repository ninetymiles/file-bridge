# Tasks

## 1. 服务层：可选配置、启动探测与超时

- [x] 1.1 在 `app/services/photo_review.py` 新增 `ReviewConfig.from_env_optional(env) -> ReviewConfig | None`（内部复用 `from_env()`，不吞掉其他异常），验证新增用例覆盖"三项齐全返回配置""缺一项返回 None""空字符串返回 None"，且既有 `from_env()` 报错用例保持不变
- [x] 1.2 在 `app/services/photo_review.py` 新增 `probe_gateway(config, timeout=3.0, http_client=None, logger=None) -> bool`：请求 `GET <base_url>/models/<quote(model, safe="")>`、携带 Bearer 认证、超时 3 秒；2xx 记 INFO 并返回 `True`，非 2xx/超时/异常记 WARNING 并返回 `False`
- [x] 1.3 用 `httpx.MockTransport` 补齐探测用例：200 返回 True、404 返回 False、连接异常返回 False，并断言请求路径为 `/v1/models/qwen3.5%3A9b`、`Authorization` 头存在，验证 `uv run pytest tests/test_photo_review.py -k probe` 全绿
- [x] 1.4 为 `PhotoReviewer` 增加可选 `timeout: httpx.Timeout | None = None`（仅在其自行创建客户端时生效，注入 `http_client` 时忽略），并把 `_encode_image` 调用改为 `await asyncio.to_thread(...)`，验证既有点评用例全部通过且请求体断言不变
- [x] 1.5 在 `app/handlers/message.py` 增加模块常量 `REVIEW_MERGE_WINDOW = 15.0`、`REVIEW_TOTAL_TIMEOUT = 60.0`、`REVIEW_CONNECT_TIMEOUT = 5.0`、`REVIEW_PREFIX = "照片点评："`，验证导入后无副作用（`uv run python -c "import app.handlers.message"` 退出码 0）

## 2. 消息链：点评任务与两段式回复

- [x] 2.1 给 `_ImageProcessResult` 增加 `saved_path: Optional[str] = None`，在 `_process_one_image` 保存成功后填入落盘路径；确认 `video`/`file`/重复/失败路径的行为不变
- [x] 2.2 给 `ReplyIntent` 增加 `after_reply: Optional[Callable[[], None]] = None`，由 `_dispatch` 在发送合并回复成功后同步调用（handler 已提前创建好等待门闩的补发任务），验证既有的 intent 合并与"无私聊兜底误发"行为不变
- [x] 2.3 实现私有 `_ReviewBatch`：`add()` 在每张照片保存后立即创建点评任务（首个请求启动时锁定 60 秒截止），`wait(timeout)` 用 `asyncio.wait` 返回已完成结果与挂起任务（不取消），`finish()` 等待剩余、到点取消并记 WARNING；空任务列表直接返回，验证单测覆盖"全部完成""部分完成""全部失败"及"截止不随后续请求推迟"
- [x] 2.4 实现 `_format_reviews(reviews: dict[int, str]) -> Optional[str]`：单条不加编号、多条按序号升序输出 `图N：…`、空结果返回 `None`，验证对应用例全绿
- [x] 2.5 在 `_handle_media` 的 `picture` 分支接入合并窗口：15 秒内取得点评则追加到 EXIF 之后（无前缀），否则返回不含点评的 intent 并设置 `after_reply` 在首次回复后补发「照片点评：…」；`video`/`file` 不创建点评任务
- [x] 2.6 在 `_handle_rich_text` 中为每张保存成功的图片立即启动点评任务，整批共用一次 15 秒窗口；补发阶段把所有成功点评合并为一条 `图N：…` 消息，失败图片的序号不出现，全部失败时不补发
- [x] 2.7 为 `MediaFileHandler` 增加 `reviewer`、`review_merge_window`、`review_timeout` 三个构造参数（默认 `None`、15.0、60.0）与 `disable_review()` 方法，验证未传 `reviewer` 时所有既有 `tests/test_media_file_handler.py` 用例行为不变

## 3. 装配、启动探测与关停

- [x] 3.1 为 `create_pipeline` 增加 `reviewer: Optional[PhotoReviewer] = None` 并透传给 `MediaFileHandler`，`app/main.py` 保持向后兼容调用
- [x] 3.2 在 `main()` 中用 `ReviewConfig.from_env_optional(os.environ)` 装配：为 `None` 时记 INFO「Photo review disabled: OPENAI_* not configured」且不构造点评器；否则构造携带 5 秒建连超时的 `PhotoReviewer`
- [x] 3.3 为 `BotService` 增加可选 `startup_hook: Callable[[], Awaitable[None]]`，在 `start()` 中于 `client.start()` 之前执行；在 `main()` 中传入探测闭包，探测失败时调用 `disable_review()`，验证 `tests/test_runner.py` 全绿且新增用例覆盖"hook 先于 SDK 启动""hook 异常不阻断启动"（或明确记录阻断策略）
- [x] 3.4 让 `MediaFileHandler.cancel_tasks()` 一并取消 `_review_tasks`，验证关停时未完成的补发任务被取消、不再发送第二条，且 `drain_active_tasks` 的既有超时语义不变

## 4. 测试：窗口赛跑与降级

- [x] 4.1 新增可控延迟的假点评器（`asyncio.Event`/`asyncio.sleep`，不连网络），用于所有两段式用例；`grep -c 'setenv\|monkeypatch' tests/test_media_file_handler.py` 输出必须为 0
- [x] 4.2 覆盖"窗口内返回 → 单条回复含点评且无前缀""窗口外返回 → 第一条无点评、第二条以「照片点评：」开头""点评超总时限 → 只发一条并记 WARNING""点评返回 None → 只发一条"
- [x] 4.3 覆盖群聊合并："3 张全部成功 → 一条点评消息含图1/图2/图3""第 2 张失败 → 只有图1与图3""全部失败 → 不补发""无保存成功图片 → 不创建点评任务"
- [x] 4.4 覆盖关闭语义：`reviewer=None` 与 `disable_review()` 后回复与今天完全一致；`cancel_tasks()` 后补发任务被取消
- [x] 4.5 运行 `uv run pytest` 全绿，确认 `tests/test_integration.py`、`tests/test_media_file_handler.py`、`tests/test_runner.py` 无回归

## 5. 文档与真实链路验证

- [x] 5.1 更新 `docs/photo-review.md`：说明消息链中的两段式行为、15 秒合并窗口、60 秒总时限、群聊合并格式、未配置/探测失败时的降级，以及"探测成功不代表模型已加载"
- [x] 5.2 在 `.env.example` 的 `OPENAI_*` 注释中补充"未配置时点评自动禁用，回复不受影响"，验证 `grep -c '^OPENAI_' .env.example` 仍为 3
- [x] 5.3 本地 `uv run python -m app.main` 启动，确认日志出现探测结论；发送一张照片确认"保存 + EXIF + 点评"单条回复；断开网关后重启确认 WARNING 且回复退回单条 EXIF
