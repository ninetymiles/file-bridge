## Why

群聊中 @ 机器人的消息当前无法与单聊获得一致处理，根因有两处：其一，群聊 @ 发送图片时钉钉平台投递的是 `richText` 消息（图片位于 `content.richText` 列表的 picture 段），而 `MediaFileHandler` 仅支持 `picture`/`video`/`file`，导致群图片既不保存也不回复；其二，`richText` 消息中携带的文本指令（如"重建索引"）当前被完全忽略，无法触发命令执行。此外，现有 `file-storage` 规范声称群聊支持 `picture`/`video`/`file`，与钉钉平台的实际投递范围不符，需要按平台事实修正。

经线上实测确认：群聊 `text` 消息的 `@机器人名` 前缀由钉钉平台自动剥离（`text.content` 仅剩前导空格），无需应用层手动归一化；`richText` 消息中 @ 提及以独立 text 段形式存在，位置不固定（可在段首或段尾）。诊断日志与日志级别配置问题已拆至独立变更 `fix-logging-configuration` 先行交付，不在本变更范围内。

## What Changes

- **richText 图片处理**：`MediaFileHandler` 支持集合加入 `richText`，从 `content.richText` 中提取所有含 `downloadCode` 的 picture 段，逐张执行既有的换取下载链接、流式下载、SHA-256 去重、落盘、元数据入库流程，并向发送者汇总回复每张图片的保存/去重结果。
- **richText 文本合并与命令解析**：`CommandHandler` 新增 `richText` 支持，将 `content.richText` 的 text 段拼接为纯文本（移除匹配 `^@\S+$` 的独立 @ 提及段、图片段替换为 `<imgN>` 语义占位符），随后执行与 `text` 消息一致的命令匹配逻辑。合并逻辑内联于 `CommandHandler`，不跨 handler 传递中间字段。
- **Pipeline 流转模型**：保留短路机制（handler 返回 `True` 终止链），但 handler 默认返回 `False` 允许消息继续流转。`richText` 消息由 `MediaFileHandler`（保存图片）与 `CommandHandler`（解析命令）依次处理，两者各自独立解析 `raw_data`，无顺序依赖、无共享中间字段。
- **平台投递范围规范化**：以钉钉官方文档与线上实测为准明确投递矩阵——单聊投递 `text`/`picture`/`video`/`file`/`richText`（多图直接选图发送会拆为多条 `picture`，加入输入框发送则合并为一条 `richText`）；群聊仅投递 @ 机器人的 `text` 与 `richText`（图片段），平台不向机器人投递群聊中的 `file`/`video`/`audio`，不做代码层面的分拣或兜底假设。
- **规范修正**：更正 `file-storage` 中"群聊支持 video/file"的错误表述。

## Capabilities

### New Capabilities
- `message-pipeline`: 机器人回调消息的接收入口规范，涵盖平台投递范围约束、`richText` 图片段提取与逐张处理、`richText` 文本语义合并与命令解析、pipeline 流转模型。

### Modified Capabilities
- `file-storage`: 修正"消息中的文件识别与异步流式下载"需求，按平台实际投递矩阵区分单聊（`picture`/`video`/`file`）与群聊（仅 `richText` 中的图片段），删除群聊支持 video/file 的不实表述。

## Impact

- **代码**：
  - `app/handlers/message.py`：`MediaFileHandler` 支持 `richText` 多图逐张处理与汇总回复；`CommandHandler` 新增 `richText` 文本合并与命令解析；pipeline 保留短路但 handler 默认返回 `False`。
- **测试**：新增 richText 单图/多图/多图含重复、无图片段的 richText、richText 文本合并与命令触发等用例；更新 `test_command_handler.py` 中 `@Bot 重建索引` 用例为平台真实形态（前导空格、无 @ 前缀）。
- **文档**：`README.md` 补充"群聊文件/视频/语音平台不投递，文件请单聊发送"的使用限制。
- **依赖**：无新增第三方依赖，无 API/配置破坏性变更。
