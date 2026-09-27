## 1. 消息入口日志分层

- [x] 1.1 扩充 `app/handlers/message.py` 的 `_dispatch()` INFO 摘要为单行元数据日志：按 `conversation_type`（"1" 单聊 / "2" 群聊，群聊附带 `conversation_title`）、发送者、消息类型组织；richText 从 `message.rich_text_content.rich_text_list` 统计段落总数与文本段/图片段数量并输出构成；file/video 在回调 `content.fileName` 存在时附带文件名（picture 无文件名字段，不输出编造名）；确保日志中不含正文、downloadCode 或链接
- [x] 1.2 在 `_dispatch()` 的 INFO 摘要之后、现有回调头/raw_data DEBUG 日志之前，新增类型化 DEBUG 正文日志（位于任何归一化/处理器链之前）：text 输出 `Text content: <正文全文>`；richText 按段落顺序逐段输出 `RichText segment[i/n]`，文本段（含 `text` 键）输出正文原文（保留群聊 @ 前缀），图片段（含 `downloadCode` 键）输出段类型与完整 downloadCode，未识别键的段落以 other keys 形式暴露；picture 输出完整 downloadCode；file/video 输出完整 downloadCode 及存在的 fileName
- [x] 1.3 在 `tests/test_pipeline.py` 用 caplog 增加用例：text 消息 INFO 无正文且 DEBUG 含正文全文；richText 消息（1 文本段 + 1 图片段）INFO 仅含段构成计数、DEBUG 含按序的两段日志与完整 downloadCode；picture 消息 INFO 无 downloadCode、DEBUG 含完整 downloadCode；运行 `uv run pytest tests/test_pipeline.py` 验证通过

## 2. 媒体下载链路 DEBUG 日志

- [x] 2.1 为 `app/services/file_downloader.py` 的 `FileDownloader` 构造函数新增可选 `logger` 参数（缺省 `logging.getLogger("file-bridge.downloader")`），并在 `app/main.py` 的 `build_pipeline()` 构造处显式传入应用 logger；确认现有测试与 `script/` 下离线脚本的无 logger 构造方式仍可用
- [x] 2.2 在 `get_download_url()` 增加换链 DEBUG 日志：请求前输出 robotCode 与完整 downloadCode，access_token 仅输出脱敏指纹（前 6 后 2 位，token 缺失时输出 unavailable）；成功后输出完整临时 downloadUrl（不截断不脱敏）；接口返回非 2xx 时先以 ERROR 输出 HTTP 状态与响应体，再走既有 `raise_for_status()` 抛出路径，不改变异常类型与上层处理
- [x] 2.3 在 `download_file_stream()` 成功返回前增加 DEBUG 日志，输出下载字节数与本地临时文件路径（失败路径不新增日志，沿用上层 ERROR 处理）
- [x] 2.4 在 `tests/test_file_downloader.py` 用 MockTransport + caplog 增加用例：换链成功时 DEBUG 含完整 downloadCode 与完整 downloadUrl、且日志中不出现完整 access_token 原文；换链返回 400 时捕获到 ERROR 日志含状态码与响应体且异常照常抛出；流式下载完成 DEBUG 含字节数与临时路径；运行 `uv run pytest tests/test_file_downloader.py` 验证通过

## 3. 整体验证

- [x] 3.1 运行 `uv run pytest` 确认全部用例通过，并运行 `openspec validate log-message-content-details --strict` 确认变更草案校验通过
- [x] 3.2 本地冒烟（合成 richText/text/picture 回调 + MockTransport，经确认可替代真机）：INFO 下摘要含群名与段构成但无正文/链接；DEBUG 下逐段正文、完整 downloadCode、完整临时 downloadUrl 依次出现，access_token 仅指纹；换链 400 场景 ERROR 含响应体。真实钉钉群聊 @ 发图文的肉眼核对随 `support-group-chat-messages` 真机验证一并完成
