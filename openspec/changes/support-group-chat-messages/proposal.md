## Why

群聊中 @ 机器人的消息当前无法与单聊获得一致处理，根因有两处：其一，群聊 @ 发送图片时钉钉平台投递的是 `richText` 消息（图片位于 `content.richText` 列表的 picture 段），而 `MediaFileHandler` 仅支持 `picture`/`video`/`file`，导致群图片既不保存也不回复；其二，群聊文本消息的 `text.content` 带有 `@机器人名 ` 字面量前缀，依赖正文精确解析的处理（如加法 fallback）在群聊中失效。此外，现有 `file-storage` 规范声称群聊支持 `picture`/`video`/`file`，与钉钉平台的实际投递范围不符，需要按平台事实修正。诊断日志与日志级别配置问题已拆至独立变更 `fix-logging-configuration` 先行交付，不在本变更范围内。

## What Changes

- **群聊文本 @ 前缀归一化**：在消息进入 handler 链之前，于 `PipelineHandler.process()` 入口对 `text` 类型消息统一剥离群聊 `@机器人名 ` 前缀（同步改写 `ChatbotMessage.text.content` 与 `raw_data["text"]["content"]`），各 handler 无感知，看到的始终是正文。
- **richText 图片处理**：`MediaFileHandler` 新增 `richText` 类型支持，从 `content.richText` 中提取所有含 `downloadCode` 的 picture 段，逐张执行既有的换取下载链接、流式下载、SHA-256 去重、落盘、元数据入库流程，并向发送者汇总回复每张图片的保存/去重结果。
- **平台投递范围规范化**：以钉钉官方文档为准明确投递矩阵——单聊投递 `text`/`picture`/`video`/`file`/`richText`；群聊仅投递 @ 机器人的 `text` 与 `richText`（图片段），平台不向机器人投递群聊中的 `file`/`video`/`audio`，不做代码层面的分拣或兜底假设。
- **规范修正**：更正 `file-storage` 中"群聊支持 video/file"的错误表述。

## Capabilities

### New Capabilities
- `message-pipeline`: 机器人回调消息的接收入口规范，涵盖平台投递范围约束、群聊文本 @ 前缀归一化、`richText` 图片段提取与逐张处理汇总回复。

### Modified Capabilities
- `file-storage`: 修正"消息中的文件识别与异步流式下载"需求，按平台实际投递矩阵区分单聊（`picture`/`video`/`file`）与群聊（仅 `richText` 中的图片段），删除群聊支持 video/file 的不实表述。

## Impact

- **代码**：
  - `app/handlers/message.py`：`process()` 入口新增 @ 前缀归一化；`MediaFileHandler` 支持 `richText` 多图逐张处理与汇总回复。
- **测试**：新增群聊文本归一化、richText 单图/多图/多图含重复、不含图片的 richText 等用例。
- **文档**：`README.md` 补充"群聊文件/视频/语音平台不投递，文件请单聊发送"的使用限制（如 README 已含环境变量章节则就地补充）。
- **依赖**：无新增第三方依赖，无 API/配置破坏性变更。日志整改（含 `LOG_LEVEL`、回调头与完整消息体诊断日志）由独立变更 `fix-logging-configuration` 先行交付，本变更的真机验证依赖其 DEBUG 诊断日志能力。
