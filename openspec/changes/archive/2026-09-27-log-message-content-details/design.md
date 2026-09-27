## Context

- 入口日志现状（`fix-logging-configuration` 已归档）：INFO 一行 `Received message from <sender>, type=<msgtype>`；DEBUG 两行回调头与完整 raw_data JSON。正文只能开 DEBUG 翻整包 JSON 看到。
- 钉钉 richText 结构（SDK 源码 `chatbot.py` 与官方文档核对）：`content.richText` 为段落 dict 列表，文本段含 `text` 键，图片段含 `downloadCode` + `"type": "picture"`；无统一 tag 字段，段落判别靠键存在性。SDK 提供 `ChatbotMessage.get_text_list()`/`get_image_list()` 辅助方法，但会丢失段落顺序与类型对应，本变更逐段遍历 `message.rich_text_content.rich_text_list`。
- 回调中的附件信息不完整：picture 消息与 richText 图片段只有 downloadCode，没有文件名；file/video 才有 fileName。
- 下载链路分三阶段：downloadCode（回调内）→ access_token + robotCode 调 `POST /v1.0/robot/messageFiles/download` 换取临时加签 downloadUrl → GET 临时 URL 下载无扩展名二进制。`FileDownloader` 当前无 logger，换链失败时 `raise_for_status()` 抛出的异常不含响应体。
- 装配点：`app/main.py` 的 `build_pipeline()` 以 `FileDownloader(output_dir=..., dingtalk_client=...)` 构造，应用 logger 已在该函数作用域内。

## Goals / Non-Goals

**Goals:**

- INFO 摘要一眼看出"谁、在单聊还是哪个群、发了什么类型、richText 段落构成/文件名"，且不含正文。
- DEBUG 下文本正文、richText 逐段内容、downloadCode、换链临时 URL、下载结果完整可追踪，支撑全链路排障。
- 改动仅限日志，不触碰处理链分支、下载业务与错误处理语义。

**Non-Goals:**

- 群聊 @ 前缀归一化、richText 图片落盘——归 `support-group-chat-messages`。
- 新增日志开关或日志级别体系（沿用已归档的 `LOG_LEVEL`）。
- README 等用户文档更新。
- audio 消息（平台投递范围有限，当前处理链不支持）。

## Decisions

1. **正文一律 DEBUG，元数据留 INFO（用户决策）。** 正文包括 text 全文、richText 文本段；downloadCode、临时 downloadUrl 也只在 DEBUG。INFO 摘要保留 richText 段计数与构成（"2 segments (1 text, 1 picture)"）及 file/video 文件名，这些属于消息元数据而非正文。
2. **临时 downloadUrl 全文进 DEBUG、不脱敏（用户决策）。** 理由：DEBUG 仅在流程故障、需要全链路分析时临时开启；downloadUrl 是一次性临时加签链接，敏感度与已在 DEBUG 全文输出的 raw_data（含 downloadCode、sessionWebhook）同级。downloadCode 同样全文输出。
3. **access_token 是唯一例外，只输出脱敏指纹**（如前 6 后 2 位），即使在 DEBUG 下也不输出全文。它是可用 client_id/secret 独立重放的根凭证、有效期约 2 小时且与具体消息无关，排障换链问题只需 robotCode、downloadCode 与 HTTP 响应体，不需要 token 全文。此条与决策 2 不矛盾：临时能力链接全文可打，根凭证不打。
4. **richText 日志逐段、保序，不用 SDK 的 get_text_list/get_image_list。** 形如 `RichText segment[1/2] text: ...`、`RichText segment[2/2] picture: downloadCode=...`，排障时可与 raw_data 段落一一对应；段落内未识别的键 DEBUG 原样附带（`other keys: [...]`），便于平台未来扩展字段时在日志中暴露。
5. **类型化正文日志紧跟 INFO 摘要之后输出，且位于任何处理与归一化之前。** 入口日志顺序固定为：INFO 元数据摘要 → DEBUG 类型化正文 → DEBUG 回调头 → DEBUG 完整 raw_data。单聊与群聊一致，正文行按类型命名：

   ```
   # 单聊文本
   INFO  Received private message from 李四, type=text
   DEBUG Text content: 你好
   DEBUG Callback headers: {...}
   DEBUG Message raw data: {...}

   # 群聊 @ 发图文
   INFO  Received group message from 张三 in 产品交流群, type=richText, segments=2 (1 text, 1 picture)
   DEBUG RichText segment[1/2] text: @文件小助手 帮我算一下
   DEBUG RichText segment[2/2] picture: type=picture, downloadCode=mIof...（全文）
   DEBUG Callback headers: {...}
   DEBUG Message raw data: {...}

   # 单聊文件
   INFO  Received private message from 王五, type=file, filename=Q3报表.xlsx
   DEBUG File attachment: fileName=Q3报表.xlsx, downloadCode=...（全文）
   ```

   群聊 @ 前缀原文必须保留；归一化在群聊变更落地后发生在此日志之后。
6. **FileDownloader 新增可选 logger 构造参数**，缺省取 `logging.getLogger("file-bridge.downloader")`（应用 logger 子 logger，天然继承级别与格式）；`build_pipeline()` 显式传入应用 logger 保持现有装配风格。
7. **换链失败补响应体日志但不改异常契约。** 非 2xx 时先 `logger.error("messageFiles/download failed: status=%s, body=%s", ...)`，再保持 `raise_for_status()` 的既有抛出路径（错误处理、临时文件清理、失败回复均由 `MediaFileHandler` 既有逻辑负责）。
8. **不约束第三方库自身日志。** httpx/httpcore 自带的 INFO 级 `HTTP Request: <url>` 请求行可能打印完整临时 downloadUrl，但不为压制它增加应用侧配置复杂度：access_token 在请求头中、不会出现在 URL 里，签名直链是一次性临时链接，敏感度可接受。应用自身的下载细节日志仍严格遵守"仅 DEBUG 输出、token 脱敏"。

## Risks / Trade-offs

- DEBUG 日志包含完整聊天正文与可下载附件的临时链接/sessionWebhook，长期开启 DEBUG 会把敏感内容写入容器日志——通过默认 INFO、仅排障临时开启缓解，与既有 raw_data 日志策略一致。
- INFO 摘要增加群名/文件名，群名可能含敏感组织信息；这是"平时掌握消息流向"的必要代价，字段均为钉钉消息元数据。
- richText 段落结构若未来扩展新段类型（如 @、链接卡片），当前日志会以 `other keys` 暴露但不做语义解析；处理链行为不变，后续按真实投递再扩展。
- `FileDownloader` 构造签名新增参数为可选参数，现有测试与离线脚本构造点不受破坏。
