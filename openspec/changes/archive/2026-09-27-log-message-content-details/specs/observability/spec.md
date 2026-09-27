## MODIFIED Requirements

### Requirement: 回调消息诊断日志
系统 SHALL 在 DEBUG 日志级别下，为每条到达消息处理入口的回调（单聊与群聊一致）输出回调头信息（至少包含 topic 与 messageId）、完整的消息体 JSON，以及按消息类型解析的类型化正文日志；消息体输出 MUST NOT 截断，中文 MUST NOT 转义为 Unicode 序列。类型化正文日志 SHALL 覆盖：`text` 输出正文全文；`richText` 按段落顺序逐段输出，文本段输出正文原文（位于任何 @ 前缀归一化之前），图片段输出段类型与完整 `downloadCode`；`picture`、`file`、`video` 输出完整 `downloadCode`，并在回调提供时输出 `fileName`。默认 INFO 级别的消息接收摘要 SHALL 只包含会话与消息元数据（单聊/群聊类型、群标题、发送者、消息类型；richText 的段落数量与文本段/图片段构成；file/video 的文件名），MUST NOT 包含文本正文、downloadCode 或任何下载链接。默认日志级别（INFO）下，应用的 DEBUG 诊断日志与第三方库（如 WebSocket 客户端）的 DEBUG 帧日志 SHALL 默认不输出，且同一条业务日志 MUST NOT 被重复输出多次。

#### Scenario: DEBUG 级别输出完整回调
- **WHEN** 应用以 `LOG_LEVEL=DEBUG` 运行且收到一条回调消息
- **THEN** 日志中包含该消息的 topic、messageId 回调头以及完整未截断的消息体 JSON，中文以原文显示，消息中的全部字段（含群聊 richText 段落结构）均可在日志中看到

#### Scenario: 默认级别压制 DEBUG 输出
- **WHEN** 应用以默认日志级别（INFO）运行
- **THEN** 日志中不出现第三方 WebSocket 库的 DEBUG 帧收发日志，应用自身的 DEBUG 诊断日志也不输出，正常的 INFO 业务日志不受影响且只输出一次

#### Scenario: INFO 摘要只含元数据不含正文
- **WHEN** 应用以 INFO 级别运行并收到 text、picture、file 或 richText 消息
- **THEN** 接收摘要日志包含会话类型（单聊或群聊及群标题）、发送者昵称、消息类型，richText 还包含段落总数与文本段/图片段数量，file/video 还包含回调中的文件名；日志中不出现文本正文、downloadCode 或下载链接

#### Scenario: DEBUG 逐段输出 richText 内容
- **WHEN** 应用以 DEBUG 级别运行并收到一条含 1 个文本段与 1 个图片段的群聊 richText 消息
- **THEN** 日志按段落顺序分别输出文本段正文原文（含原始 `@机器人名` 前缀）与图片段的段类型和完整 downloadCode，段落可按序号与输入段落一一对应

#### Scenario: DEBUG 输出各类型正文细节
- **WHEN** 应用以 DEBUG 级别运行并分别收到 text、picture、file、video 消息
- **THEN** 日志分别包含：text 的正文全文；picture 的完整 downloadCode；file/video 的完整 downloadCode 与回调提供的 fileName（picture 回调无文件名字段时不输出编造的文件名）

## ADDED Requirements

### Requirement: 媒体下载链路诊断日志
媒体下载组件 SHALL 在 DEBUG 日志级别下输出文件下载链路的完整排障细节：调用换链接口前输出 robotCode 与完整 downloadCode，换链成功后输出返回的完整临时下载 URL（不脱敏、不截断）；access_token MUST 仅以脱敏指纹形式出现，MUST NOT 输出完整 token。换链接口返回非成功状态时，系统 SHALL 以 ERROR 级别记录 HTTP 状态与响应体后再抛出异常。流式下载完成后 SHALL 在 DEBUG 级别输出下载字节数与本地临时文件路径。默认 INFO 级别下，应用自身日志 MUST NOT 输出 downloadCode、临时下载 URL、access_token 或响应体内容；第三方 HTTP 库（如 httpx）自带的请求行日志不在本需求约束范围内，应用不为压制依赖库日志增加额外配置。

#### Scenario: DEBUG 输出换链全流程
- **WHEN** 应用以 DEBUG 级别运行且成功处理一条带附件的消息
- **THEN** 日志包含换链请求前的 robotCode 与完整 downloadCode，以及成功后返回的完整临时 downloadUrl；access_token 仅以脱敏指纹出现，日志中找不到完整 token

#### Scenario: 换链失败记录响应体
- **WHEN** 换链接口返回非 2xx 状态（如下载码过期或 robotCode 不匹配）
- **THEN** 系统以 ERROR 级别记录接口 HTTP 状态与响应体内容，随后按既有错误处理路径抛出异常，临时文件清理与失败回复行为不受影响

#### Scenario: DEBUG 输出流式下载结果
- **WHEN** 附件二进制通过临时 URL 流式下载完成
- **THEN** DEBUG 日志包含下载字节数与本地临时文件路径

#### Scenario: 默认级别应用日志不泄露下载细节
- **WHEN** 应用以默认 INFO 级别运行并完成附件下载
- **THEN** 应用自身日志中不出现 downloadCode、临时 downloadUrl、access_token 与接口响应体，业务侧既有的"开始处理/保存成功"INFO 日志行为保持不变；第三方 HTTP 库自身输出的请求行不属本场景断言范围
