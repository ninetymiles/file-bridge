## Why

当前消息处理链路采用短路责任链模型：处理器返回 `True` 终止处理链，返回 `False` 继续流转。这一设计导致单聊纯文本消息绕过 `CommandHandler` 后仍落入 `MediaFileHandler` 的不支持类型分支，产生两条回复（命令结果/引导 + "暂不支持该类型"）；同时 `MediaFileHandler` 承担了对 `audio` 等不支持类型的兜底回复，回复职责与消息类型判断逻辑错位。本变更引入分层回复意图模型，使回复生成职责从处理器收拢到 Dispatcher，根治双回复问题。

## What Changes

- **引入 `ReplyIntent` 意图对象**：处理器不再返回 `bool`，而是返回 `Optional[ReplyIntent]`（`None` 表示"非我职责"）。意图包含完整措辞的回复文本与一个优先级层级；层级仅表达通用投递优先级、不耦合内容类型，当前定义 `PRIMARY`（高优先级，用于保存结果、命令执行结果等确定性内容）与 `SECONDARY`（低优先级，用于命令未命中的使用引导等建议性内容）。
- **所有处理器运行至完成，不再短路**：每个处理器独立返回意图，不依赖执行顺序，也不提前终止处理链。
- **Dispatcher 统一汇总并发送回复**：收集全部意图后按优先级裁决——取最高优先级层级，该层级全部文本以 `"\n"` 合并为一条消息发送，更低层级一律抑制；无任何意图时由 Dispatcher 按消息类型产生真正兜底回复（单聊语音→语音不支持提示，单聊其他未知类型→通用不支持提示，群聊→静默 ACK）。
- **删除 `MediaFileHandler` 的不支持类型分支**：`audio` 与未知类型的回复职责上移至 Dispatcher，处理器仅处理其职责范围内的媒体保存。
- **删除 `CommandHandler` 的含图抑制逻辑**：命令未命中时无条件返回 `SECONDARY` 意图（含图片段的消息同样返回），最终是否发送由 Dispatcher 按层级裁决决定，消除处理器间的隐式耦合。
- **新增合并回复场景**：`richText` 同时含图片段与命中命令时，图片保存结果与命令执行结果合并为单条消息回复，而非当前的两条独立气泡。

## Capabilities

### New Capabilities

无。本变更未引入新的业务领域能力，仅重构现有 pipeline 的回复组合机制。

### Modified Capabilities

- `message-pipeline`：重写 "Pipeline 流转模型" 要求（从短路责任链改为意图报告链，含"低优先级层级向高优先级层级让位"的 Dispatcher 裁决规则）；修改 "不支持消息类型的明确回复" 要求（从 `MediaFileHandler` 分支移至 Dispatcher 真正兜底）；新增 Scenario：媒体结果与命令结果合并为单条回复。

## Impact

- **代码**：`app/handlers/message.py`（`BaseMessageHandler.handle` 返回签名、`CommandHandler`、`MediaFileHandler`、`PipelineHandler._dispatch` 回复逻辑重构），常量 `UNSUPPORTED_AUDIO_TEXT` / `UNSUPPORTED_TYPE_TEXT` 从 `MediaFileHandler` 移至 Dispatcher。
- **行为变化（BREAKING）**：`richText` 同时触发图片保存与命令命中时，当前产生两条独立回复气泡，变更后合并为一条消息；单聊 `audio` 当前由 `MediaFileHandler` 回复，变更后由 Dispatcher 回复（内容不变）。
- **依赖、配置、数据库**：无变更。
- **测试**：需补充单聊文本单回复验证、`richText` 含图+命令合并回复验证、audio/未知类型 Dispatcher 兜底验证、群聊静默 ACK 验证、缺失 downloadCode 兜底验证。
