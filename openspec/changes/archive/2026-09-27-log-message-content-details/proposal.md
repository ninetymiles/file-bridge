## Why

当前消息入口在默认 INFO 级别下只输出"发送者 + 消息类型"，排查消息问题时必须开 `LOG_LEVEL=DEBUG` 翻阅多行完整 payload JSON 才能看到文本正文、群聊 richText 的段落构成；而媒体下载链路（downloadCode 换取临时直链、流式下载）所在的 `FileDownloader` 完全没有日志，换链失败或下载异常时无法定位发生在"取 token / 换链 / 下载"的哪一环。需要在不改变默认 INFO 安静度的前提下，把排障所需的正文与下载细节按级别分层输出。

## What Changes

- **入口 INFO 摘要扩充为会话与消息元数据**（不含正文）：区分单聊/群聊（会话类型、群标题）、发送者、消息类型；richText 增加段落构成计数（文本段数、图片段数）；file/video 携带回调中的文件名（picture 回调无文件名字段，不编造）。
- **入口新增 DEBUG 级类型化正文日志**：text 输出正文全文；richText 按段落顺序逐段输出——文本段输出正文原文（保留群聊 `@机器人名` 前缀，位于任何归一化之前），图片段输出段类型与完整 `downloadCode`；picture/file/video 输出 `fileName`（若有）与完整 `downloadCode`。完整 raw_data JSON 日志保持不变作为兜底。
- **下载链路新增 DEBUG 全流程日志**：`FileDownloader` 注入应用 logger；换取临时直链前输出 robotCode、完整 downloadCode（access_token 仅输出脱敏指纹），成功后输出完整临时 `downloadUrl`（不脱敏、不截断——DEBUG 仅在排障时开启，临时直链是一次性加签链接）；换链接口返回非 2xx 时以 ERROR 记录响应体再抛出；流式下载完成后输出字节数与临时文件路径。不为压制 httpx 等依赖库自带请求日志增加额外配置。
- **不做的事**：不改变消息处理与下载业务逻辑；不做群聊 @ 前缀归一化（归 `support-group-chat-messages`）；不实现 richText 图片落盘（归群聊变更）；不修改 README。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `observability`: 修改「回调消息诊断日志」需求（INFO 摘要明确只含元数据；DEBUG 增加按消息类型解析的正文与 richText 段落级日志），新增「媒体下载链路诊断日志」需求（换链与流式下载的 DEBUG 细节、失败响应体记录）。

## Impact

- **代码**：
  - `app/handlers/message.py`：`_dispatch()` 入口 INFO/DEBUG 日志扩充，richText 段落遍历（读取 `message.rich_text_content.rich_text_list`，以键存在性区分文本段/图片段）。
  - `app/services/file_downloader.py`：构造函数新增 `logger` 参数；`get_download_url()` 增加换链前后 DEBUG 日志与失败 ERROR；`download_file_stream()` 增加完成 DEBUG 日志。
  - `app/main.py`：`build_pipeline()` 构造 `FileDownloader` 时传入应用 logger。
- **测试**：`tests/test_pipeline.py` 用 caplog 覆盖 text/richText/picture 三类消息的 INFO 无正文、DEBUG 含正文与段落细节；`tests/test_file_downloader.py` 用 MockTransport + caplog 覆盖换链成功的全文 URL 日志、非 2xx 的 ERROR 响应体、流式完成日志。
- **依赖**：无新增第三方依赖，无配置变更；默认 INFO 行为除摘要信息增多外不输出任何正文/凭证/链接。
