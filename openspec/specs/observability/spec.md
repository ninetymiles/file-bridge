# observability Specification

## Purpose

定义应用运行期的诊断可观测性要求，使排障时能够在 DEBUG 日志级别下查看每条钉钉回调的回调头与完整消息体，同时保证默认运行级别安静、不被第三方库 DEBUG 日志干扰。

## Requirements

### Requirement: 回调消息诊断日志
系统 SHALL 在 DEBUG 日志级别下，为每条到达消息处理入口的回调（单聊与群聊一致）输出回调头信息（至少包含 topic 与 messageId）以及完整的消息体 JSON；消息体输出 MUST NOT 截断，中文 MUST NOT 转义为 Unicode 序列。默认日志级别（INFO）下，应用的 DEBUG 诊断日志与第三方库（如 WebSocket 客户端）的 DEBUG 帧日志 SHALL 默认不输出，且同一条业务日志 MUST NOT 被重复输出多次。

#### Scenario: DEBUG 级别输出完整回调
- **WHEN** 应用以 `LOG_LEVEL=DEBUG` 运行且收到一条回调消息
- **THEN** 日志中包含该消息的 topic、messageId 回调头以及完整未截断的消息体 JSON，中文以原文显示，消息中的全部字段（含群聊 richText 段落结构）均可在日志中看到

#### Scenario: 默认级别压制 DEBUG 输出
- **WHEN** 应用以默认日志级别（INFO）运行
- **THEN** 日志中不出现第三方 WebSocket 库的 DEBUG 帧收发日志，应用自身的 DEBUG 诊断日志也不输出，正常的 INFO 业务日志不受影响且只输出一次
