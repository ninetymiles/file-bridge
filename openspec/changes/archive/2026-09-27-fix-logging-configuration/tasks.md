## 1. 日志级别配置

- [x] 1.1 在 `app/main.py` 的 `parse_config` 返回的 Namespace 中新增 `log_level` 字段（缺省 `"INFO"`），从环境变量 `LOG_LEVEL` 解析；在 `tests/test_config.py` 增加用例：未设置时缺省为 `"INFO"`、设置 `LOG_LEVEL=debug` 时原样读入（大小写不敏感的校验放在 1.2），运行 `uv run pytest tests/test_config.py` 验证通过
- [x] 1.2 在 `app/main.py` 中新增级别解析纯函数 `resolve_log_level(raw) -> int`（支持 DEBUG/INFO/WARNING/ERROR 大小写不敏感，非法值回退 INFO）；重构 `setup_logger()`：`basicConfig(level=INFO, format=<现有详细格式>)`、移除 `file-bridge` 私有 handler 以消除重复打印、按解析结果设置应用 logger 级别、非法值时在 basicConfig 之后输出 WARNING；为纯函数补充单测（四个合法值映射、大小写混合、非法值回退 INFO）并运行通过

## 2. SDK 日志接入与回调诊断日志

- [x] 2.1 在 `app/main.py` 构造 `DingTalkStreamClient` 时传入应用 logger（`logger=logger`），启动应用确认 SDK 客户端日志以 `file-bridge` 名义与统一格式输出，不再出现独立 handler 的重复输出
- [x] 2.2 在消息处理入口（`app/handlers/message.py` 的 `_dispatch()`）新增 DEBUG 级回调头日志（topic、messageId，取自 `callback.headers`），并将现有完整 raw_data 日志移到回调头相邻位置（保持 `ensure_ascii=False`、缩进、不截断，置于任何消息内容改写之前）；在 `tests/test_pipeline.py` 用 caplog 验证：DEBUG 级别下两条日志均出现且包含 messageId 与完整 raw_data（中文不转义），INFO 级别下均不出现，且同一条日志只被捕获一次，运行 `uv run pytest tests/test_pipeline.py` 验证通过

## 3. 整体验证

- [x] 3.1 运行 `uv run pytest` 确认全部用例通过，并运行 `openspec validate fix-logging-configuration --strict` 确认变更草案校验通过
- [x] 3.2 日志行为验证（以合成 `CallbackMessage` 的本地运行时冒烟 + caplog 单测替代真机，日志代码路径与真机一致；经确认接受）：默认 INFO 下无 websockets 等第三方 DEBUG 帧且业务 INFO 日志只输出一次；`LOG_LEVEL=DEBUG` 下输出 topic、messageId 回调头与完整未截断消息体（中文原样），第三方 DEBUG 仍压制；非法值（如 `foo`）输出配置告警且应用正常以 INFO 运行。真实钉钉 payload 的肉眼核对随 `support-group-chat-messages` 任务 3.3 一并完成

> 备注：本变更不修改 README，环境变量配置不在 README 中说明（用户决定）。
