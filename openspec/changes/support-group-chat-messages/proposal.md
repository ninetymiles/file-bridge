## Why

群聊中 @ 机器人的消息当前无法与单聊获得一致处理，根因有三处：其一，群聊 @ 发送图片时钉钉平台投递的是 `richText` 消息（图片位于 `content.richText` 列表的 picture 段），而 `MediaFileHandler` 仅支持 `picture`/`video`/`file`，导致群图片既不保存也不回复；其二，群聊文本消息的 `text.content` 带有 `@机器人名 ` 字面量前缀，依赖正文精确解析的处理（如加法 fallback）在群聊中失效；其三，诊断日志形同虚设——root logger 被设为 DEBUG 导致 `websockets` 等第三方库的截断帧日志刷屏，而应用自身记录完整消息体的 DEBUG 日志因 `file-bridge` logger 被钉在 INFO 而永远不会输出，排查时拿不到完整 payload。此外，现有 `file-storage` 规范声称群聊支持 `picture`/`video`/`file`，与钉钉平台的实际投递范围不符，需要按平台事实修正。

## What Changes

- **群聊文本 @ 前缀归一化**：在消息进入 handler 链之前，于 `PipelineHandler.process()` 入口对 `text` 类型消息统一剥离群聊 `@机器人名 ` 前缀（同步改写 `ChatbotMessage.text.content` 与 `raw_data["text"]["content"]`），各 handler 无感知，看到的始终是正文。
- **richText 图片处理**：`MediaFileHandler` 新增 `richText` 类型支持，从 `content.richText` 中提取所有含 `downloadCode` 的 picture 段，逐张执行既有的换取下载链接、流式下载、SHA-256 去重、落盘、元数据入库流程，并向发送者汇总回复每张图片的保存/去重结果。
- **平台投递范围规范化**：以钉钉官方文档为准明确投递矩阵——单聊投递 `text`/`picture`/`video`/`file`/`richText`；群聊仅投递 @ 机器人的 `text` 与 `richText`（图片段），平台不向机器人投递群聊中的 `file`/`video`/`audio`，不做代码层面的分拣或兜底假设。
- **诊断日志整改**：每条回调在 DEBUG 级输出 `callback.headers`（topic、messageId 等）与完整消息体（`raw_data` 全量，不截断）；`setup_logger()` 调整为 root logger 默认 INFO（压制第三方库 DEBUG 噪音），`file-bridge` 应用 logger 级别由新增环境变量 `LOG_LEVEL` 控制（默认 INFO，排查时设为 DEBUG）；`DingTalkStreamClient` 构造时传入应用 logger，统一 SDK 与应用日志格式。
- **规范修正**：更正 `file-storage` 中"群聊支持 video/file"的错误表述；`bot-config` 增加 `LOG_LEVEL` 配置需求。

## Capabilities

### New Capabilities
- `message-pipeline`: 机器人回调消息的接收入口规范，涵盖平台投递范围约束、群聊文本 @ 前缀归一化、`richText` 图片段提取与逐张处理汇总回复、以及完整消息诊断日志要求。

### Modified Capabilities
- `file-storage`: 修正"消息中的文件识别与异步流式下载"需求，按平台实际投递矩阵区分单聊（`picture`/`video`/`file`）与群聊（仅 `richText` 中的图片段），删除群聊支持 video/file 的不实表述。
- `bot-config`: 新增日志级别配置需求，支持通过环境变量 `LOG_LEVEL` 控制应用日志级别。

## Impact

- **代码**：
  - `app/main.py`：重构 `setup_logger()`（root INFO、应用 logger 级别可配）、向 `DingTalkStreamClient` 传入应用 logger。
  - `lib/config.py`：`AppConfig` 新增 `log_level` 字段，解析 `LOG_LEVEL` 环境变量（默认 `INFO`）。
  - `lib/handlers.py`：`process()` 入口新增 @ 前缀归一化与 headers+raw_data 完整日志；`MediaFileHandler` 支持 `richText` 多图逐张处理与汇总回复。
- **测试**：新增群聊文本归一化、richText 单图/多图/多图含重复、不含图片的 richText 等用例；更新日志相关测试。
- **文档**：`README.md` 补充 `LOG_LEVEL` 说明与"群聊文件/视频/语音平台不投递，文件请单聊发送"的使用限制（如 README 已含环境变量章节则就地补充）。
- **依赖**：无新增第三方依赖，无 API/配置破坏性变更（`LOG_LEVEL` 缺省行为保持 INFO）。
