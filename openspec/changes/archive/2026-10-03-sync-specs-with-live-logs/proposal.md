## Why

2026-10-03 线上实测日志（log1/log2/log3，Android 端）与现有 spec 比对后发现：spec 未登记若干平台实际投递的消息结构（单聊 video 的 `duration`/`videoType` 字段、单聊纯文本 richText 消息），且视频分辨率格式化符号的 spec 表述（`×`）与实现及日志实际输出（`x`）不一致。spec 作为设计与实现基准，需与线上实测保持同步。

## What Changes

- 在 `message-pipeline` 的"平台消息结构约定"中补充单聊 video 消息结构 Scenario：负载含 `downloadCode`、`duration`（字符串秒数）、`videoType`（如 `mp4`），不含 `fileName`
- 在 `message-pipeline` 中补充单聊纯文本 richText Scenario：单聊中随视频发送的文本以独立 `richText` 消息投递（与 video 消息分离），不含图片段；不带文本时平台可能额外投递仅含换行段的空 richText 帧，按空文本处理
- 在"群聊视频产生空 richText 帧"Scenario 补充说明：@ 提及段位置由用户发送时编辑决定，不固定（实测样本中位于段尾）
- 将 `media-metadata` 中视频分辨率格式化符号由 `×` 统一为字母 `x`（与实现及日志输出一致）

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `message-pipeline`: 补充单聊 video 与单聊纯文本 richText 的消息结构实测样本，澄清群聊视频空帧 @ 段位置不固定
- `media-metadata`: 视频分辨率摘要格式由 `宽×高` 修正为 `宽x高`

## Impact

- 仅 spec 文档更新；现有实现与日志行为已一致，无需代码变更
- 影响文档：`openspec/specs/message-pipeline/spec.md`、`openspec/specs/media-metadata/spec.md`
