## 1. 启动版本与配置摘要

- [x] 1.1 在 `app/main.py` 实现 `get_app_version() -> str`：`os.getenv("APP_VERSION") or "dev"`（空串回退 `dev`，不读任何文件）。同时在 `Dockerfile` 增加 `ARG APP_VERSION=dev` 与 `ENV APP_VERSION=$APP_VERSION`；在 `.github/workflows/docker-buildx.yml` 的 build-push 步骤增加 `build-args: APP_VERSION=${{ steps.meta.outputs.version }}`；清理 `pyproject.toml` 的 `[project]` 表，删除 `description`/`readme`，`version` 保留原值 `1.0.0` 加注释（uv/PEP 621 强制要求，运行时不读）。以单测验证：`APP_VERSION=1.2.3` 返回 `1.2.3`；`APP_VERSION` 为空串或未设置时返回 `dev`；`uv sync` 在精简后的 pyproject 下仍正常
- [x] 1.2 在 `app/main.py` 实现 `log_startup_summary(config, logger)`：输出版本行（`File Bridge starting: version=<APP_VERSION 或 dev>`）与配置行（client_id 明文、log_level、semantic_command 开关及关闭时的 substring 模式、notify_staff/notify_group 开关并附带已配置 id、output_dir）；摘要中 MUST NOT 出现 client_secret。在 `main()` 的 `setup_logger` 之后、Credential 创建之前接线。以 caplog 契约测试验证：全字段开启/关闭两种配置的输出、client_id 可见、secret 永不出现

## 2. 接收/下载/回复 INFO 日志

- [x] 2.1 在 `app/handlers/message.py` 将 richText 合并逻辑提为模块级 `merge_rich_text_segments(segments)`（行为不变），`CommandHandler._merge_rich_text` 改为薄委托静态方法；验证现有 `test_command_handler` 4 个合并测试零改动通过
- [x] 2.2 修改 `_log_received_message`：text 与 richText 的 INFO 接收摘要追加 `content=<正文>`（richText 无文本段时即 `<img1>`），其他类型不增加正文字段；删除 text 的 `Text content` DEBUG 与 richText 文本段 DEBUG（图片段/其他段 downloadCode 明细、raw payload、回调头 DEBUG 保留）。以 caplog 测试验证：text 正文、图文 richText 合并文本、纯图片 richText 的 `<img1>` 在 INFO 可见；picture/audio 无 content 字段；INFO 中不出现 downloadCode
- [x] 2.3 在 `MediaFileHandler._process_one_image` 创建下载任务之前输出一条 INFO（`Downloading file: type=<msgtype>, name=<original_filename>`），每个媒体恰好一次、不含 code/URL/token；验证现有 `test_resolve_url_info_level_hides_codes_and_url` 仍通过，并新增 richText 双图产生两条下载日志的断言
- [x] 2.4 在 `PipelineHandler.async_reply_text` 增加回复日志：**先 `await to_thread(reply_text, ...)` 再记录日志**——成功时 INFO（回复目标 private/group + 发送者或群名 + 完整文本），SDK 返回 None 时 WARNING；以测试验证普通回复与存储唤醒提示均留下 INFO、失败路径产生 WARNING（用 reply_text 返回 None 驱动），并验证唤醒提示路径下 DingTalk 发送调用先于 INFO 日志调用（mock 顺序断言）

## 3. SDK 连接日志整形与 HTTP 噪音收敛

- [x] 3.1 在 `app/main.py` 的 `setup_logger()` 中实现并挂载日志 Filter（挂到 root 的 StreamHandler）：仅对 `name=file-bridge`、`filename=stream.py` 的记录生效——`received disconnect topic=disconnect` 改写为 INFO 结论行 `DingTalk stream disconnected: received disconnect message`（剥离原始 JSON）；`endpoint is ` 改写为 `DingTalk stream connected.`；`open connection, url=` 降级为 DEBUG；其余记录原样放行。同时将 `httpx` logger 设为 WARNING。以合成 LogRecord 单测验证四条规则（两条改写、一条降级、无关记录放行）
- [x] 3.2 验证 INFO 级别下不再出现 httpx 逐请求日志（组合测试中跑通媒体消息后断言 caplog 无 `HTTP Request:` 记录），DEBUG 级过滤细节保持可输出

## 4. 全量回归与变更校验

- [x] 4.1 运行 `uv run pytest`（general 集）确认无回归；复核 test_integration 全部消息类型链路断言、drain 行为、配置测试不受影响
- [x] 4.2 运行 `openspec validate refine-info-logging --strict` 通过
