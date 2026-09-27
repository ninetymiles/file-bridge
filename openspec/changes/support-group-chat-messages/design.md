## Context

See proposal.md - Why。当前消息处理链为 `DingTalkStreamClient.route_message()` → `PipelineHandler.process(callback)` → 顺序执行 `CommandHandler`、`MediaFileHandler`、`CalcBotFallbackHandler`（见 `lib/handlers.py`）。已确认的平台与代码事实：

- 钉钉平台投递矩阵：单聊投递 `text`/`picture`/`video`/`file`/`richText`；群聊仅投递 @ 机器人的 `text` 与 `richText`，群聊图片在 `content.richText` 列表中以 `{type: picture, downloadCode: ...}` 段落投递；群聊 `file`/`video`/`audio` 平台不投递（官方《消息发送与接收类型》《机器人接收消息》文档）。
- 群聊文本的 `text.content` 带 `@机器人名 ` 字面量前缀；现有处理器同时从 `message.text.content` 与 `raw_data["text"]["content"]` 两处读正文。
- SDK 已解析 `ChatbotMessage.rich_text_content.rich_text_list`，但其 `from_dict()` 在遍历到 `msgtype` 键时即时读取 `d['content']`，对键顺序有隐含依赖；原始字典 `raw_data` 始终完整可用。
- 日志现状：`app/main.py` 中 `basicConfig(level=DEBUG)` 将 root logger 置为 DEBUG（第三方库 DEBUG 帧日志刷屏），同时 `file-bridge` logger 被私有 handler 重复挂载并钉在 INFO（应用 DEBUG 日志沉默、每条 INFO 日志打印两遍）；`DingTalkStreamClient` 构造时未传入应用 logger。
- `save_file()` 命名含毫秒时间戳与撞名自增计数器，同消息多图不会撞名。

## Goals / Non-Goals

**Goals:**

- 群聊 @ 文本在进入处理器链前完成 @ 前缀归一化，处理器对单聊/群聊正文无差别处理。
- `MediaFileHandler` 支持 `richText` 图片段：多图逐张走既有下载/去重/落盘/入库流程，一条汇总回复。
- 日志配置可观测、可配置：默认安静（INFO），`LOG_LEVEL=DEBUG` 时能看到回调头与完整消息体。
- 不改变单聊 `picture`/`video`/`file` 既有处理行为与去重语义。

**Non-Goals:**

- 不实现群聊文件/视频/语音接收（平台不投递，无回调可处理）。
- 不让 `richText` 中的文本段参与"重建索引"或加法解析（群聊纯文本由 `text` 类型投递）。
- 不新增群内"文件请单聊发送"主动引导文案（后续产品决策）。
- 不改动 SDK 本体与第三方库日志行为，不 pin/升级 `websockets` 版本。

## Decisions

### 决策 1：@ 前缀在 process() 入口单点归一化

在 `PipelineHandler.process()` 构造 `ChatbotMessage` 之后、处理器链执行之前，对满足以下全部条件的消息执行剥离：`conversation_type == "2"`（群聊）、`message_type == "text"`、且 `is_in_at_list` 为真。剥离逻辑抽为纯函数（如 `strip_robot_at_prefix(content: str) -> str`），规则：去除开头空白 → 去除首个 `@提及段`（`@` 起至其后第一个空白字符止）→ 去除紧随空白；不匹配则原样返回。

归一化结果**同时写回** `incoming_message.text.content` 与 `raw_data["text"]["content"]`，因为现有处理器两条读取路径都在用，只改一处会造成不一致。

- 备选 A：在每个 handler 内部各自 strip。被否：三处重复、易漏、CalcBotFallbackHandler 与未来新处理器都要记得做。
- 备选 B：用 `is_in_at_list` 做消息分拣门槛直接丢弃未 @ 消息。被否：平台已保证只投递 @ 消息，分拣是冗余且会误伤未来平台行为变化。
- 仅对群聊生效，单聊内容绝不改写。

### 决策 2：richText 以 raw_data 为权威数据源，复用单图处理内核

`MediaFileHandler` 的支持集合加入 `richText`。提取时直接遍历 `raw_data["content"]["richText"]`，取所有含 `downloadCode` 键的段落，不依赖 SDK 的 `rich_text_content` 对象（规避 `from_dict()` 的键顺序隐含依赖，与该 handler 现有"优先 raw_data"风格一致）。

将现有单图处理体抽取为内部协程（如 `_process_one_image(download_code, original_filename, default_ext, message, raw_data)`），返回结构化逐图结果（saved / duplicate / failed + 详情），`picture` 路径与 `richText` 路径共用：

- `picture`：行为与现状完全一致，单图单回复。
- `richText`：无图片段 → `return False` 放行后续处理器；有图片段 → 逐张处理，全部完成后**一条**汇总回复，每张一行。多图的缺省文件名按序号命名为 `picture_1.png`、`picture_2.png`……便于在汇总回复中对应；落盘仍由 `save_file()` 的时间戳+撞名计数器保证唯一。
- 逐图独立 try/except：单张失败记录 failed 状态并继续其余图片，整条消息不抛未捕获异常（与现有"异常也 ACK OK"策略一致）。
- 同一消息内两张相同图片天然被既有"逐次查重"逻辑覆盖：第一张保存、第二张回复"已存在"。
- `richText` 中的文本段一律忽略（见 Non-Goals）；未来若出现新段类型，不含 `downloadCode` 即被跳过，天然兼容。

### 决策 3：日志整改为"root INFO + 应用 logger 可配"，完整回调在 DEBUG 输出

`setup_logger()` 重构：

1. `logging.basicConfig(level=logging.INFO, format=<现有详细格式>)`：root 统一 INFO 与格式，移除 `file-bridge` 私有 handler（消除每条日志打印两遍），利用日志向上传播由 root handler 统一输出。
2. 级别解析抽纯函数（如 `resolve_log_level(raw) -> int`）：映射 DEBUG/INFO/WARNING/ERROR（大小写不敏感），非法值回退 `INFO`；`file-bridge` logger 按解析结果 `setLevel`，非法时在 basicConfig 之后输出一条 WARNING。Python 日志的级别过滤只在发起记录的 logger 上发生一次、向父 handler 传播时不再过滤，因此 file-bridge=DEBUG 时应用 DEBUG 可见，而 `websockets` 等未设级别的第三方 logger 有效级别继承 root=INFO，其 DEBUG 帧日志继续被压制。
3. `DingTalkStreamClient(credential, logger=logger)`：SDK 客户端日志并入应用 logger，统一格式与级别管控。
4. `process()` 入口在现有 INFO 摘要之外，DEBUG 级新增两行：回调头（topic、messageId）与完整 `raw_data` JSON（`ensure_ascii=False, indent=2, default=str`，即现有第 250 行日志上移并补 headers），不做任何截断。

`app/main.py` 的 `parse_config` 返回的 Namespace 新增 `log_level` 字段（缺省 `"INFO"`），仅从环境变量 `LOG_LEVEL` 读取（不增加命令行参数，保持与 OUTPUT_DIR 等运行时配置一致的环境变量方式）。注：`lib/config.py` 已由变更 simplify-config-entry 内联至 `app/main.py`，`AppConfig` 已移除。

- 备选：保留私有 handler + `propagate=False`。被否：双 handler 是当前重复打印的根因，统一到 root 更简单，且 FastAPI/Uvicorn 接入后（见在途变更 integrate-fastapi-framework）日志也天然统一。

### 决策 4：平台限制只做规范化，不做补偿逻辑

群聊收不到文件/视频/语音是平台投递侧限制，代码无法感知"用户曾经尝试发文件"，因此不做轮询、不做伪触发，仅在 spec/README 中写明限制与"文件请单聊发送"的使用说明。

## Risks / Trade-offs

- [剥离规则假设机器人显示名不含空白字符（正则切到第一个空格）] → 以 `is_in_at_list` + 群聊 + text 三重前提收窄适用面；机器人名含空格时剥离失败会**退化回当前现状**（"重建索引"子串匹配仍可用），不会比现在更差；上线后用 DEBUG 日志抓真实文本形态再固化规则（见 Open Questions）；若后续证实名字可含空格，备选方案是通过会话/机器人信息 OpenAPI 反查显示名做精确前缀匹配。
- [`LOG_LEVEL=DEBUG` 时完整消息体进入日志，其中含 `sessionWebhook` 地址与 `downloadCode`] → 默认级别 INFO 不输出；DEBUG 仅排障时临时开启，与容器内本地日志同等敏感度。
- [多图汇总回复可能超过消息长度上限] → 单条富文本图片数量实际很小（钉钉客户端一次发送图片数量有限），当前不做分条；若日后出现超长，再按条数切分回复，接口形态不变。
- [默认日志级别变化导致排障习惯改变（不再默认看到 SDK DEBUG）] → 属本次目的；README 写明 `LOG_LEVEL=DEBUG` 用法。

## Migration Plan

1. 无数据迁移、无新增依赖；合入后重新构建镜像/重启即可生效，缺省 `LOG_LEVEL` 行为为 INFO。
2. 建议上线后临时以 `LOG_LEVEL=DEBUG` 在调试群实测：群聊 @ 发一条文本、一条单图、一条多图，核对 @ 前缀真实字面量与 `richText` 段落结构，确认剥离规则与提取逻辑（回答 Open Questions）。
3. 回滚：还原代码即可；`LOG_LEVEL` 为可选环境变量，回滚后无残留配置影响。

## Open Questions

- 群聊文本 `text.content` 中 @ 前缀的精确字面量（普通空格还是不间断空白、机器人显示名是否允许含空格、被 @ 名与正文间有几个空白字符）：不改变归一化位置、写回策略与任务拆分，仅影响剥离纯函数的最终正则形态，按 Migration Plan 第 2 步实测后固化。
