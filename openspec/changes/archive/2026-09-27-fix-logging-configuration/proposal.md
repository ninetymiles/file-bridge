## Why

当前日志配置逻辑反转：`app/main.py` 的 `setup_logger()` 用 `logging.basicConfig(level=DEBUG)` 把 root logger 置为 DEBUG，导致 `websockets` 等第三方库的 DEBUG 帧日志刷屏；同时 `file-bridge` 应用 logger 被钉在 INFO 且重复挂载私有 handler，应用自身的 DEBUG 诊断日志（如消息入口已存在的完整消息体日志）永远不会输出，且每条 INFO 日志经 root 与私有两个 handler 打印两遍。排查消息问题时既看不到应用 DEBUG 信息，又被第三方噪音淹没。该整改原含于在途变更 `support-group-chat-messages`，现拆为独立变更先行交付，使群聊/单聊功能调整不再与日志整改耦合。

## What Changes

- **日志级别反转修正**：`basicConfig` 默认级别改为 INFO 并统一日志格式，root logger 负责压制第三方库 DEBUG 噪音；移除 `file-bridge` logger 的私有 StreamHandler，日志向上传播由 root handler 单点输出，消除每条日志打印两遍。
- **应用日志级别可配**：新增环境变量 `LOG_LEVEL`（取值 DEBUG/INFO/WARNING/ERROR，大小写不敏感，缺省 INFO），仅控制 `file-bridge` 应用 logger 级别；非法值回退 INFO 并输出一条配置告警，不阻止启动。
- **SDK 日志并入**：构造 `DingTalkStreamClient` 时传入应用 logger，SDK 日志与应用日志统一格式、统一受级别管控。
- **回调诊断日志补齐**：`PipelineHandler` 消息入口在现有 INFO 摘要之外，DEBUG 级输出回调头（topic、messageId）与完整消息体 JSON（已有的 raw_data 日志归位至回调头旁，不截断、中文不转义）。

## Capabilities

### New Capabilities

- `observability`: 运行期可观测性规范，覆盖回调入口在 DEBUG 级别下的回调头与完整消息体诊断日志，以及默认 INFO 级别对应用诊断日志与第三方库 DEBUG 噪音的压制要求。

### Modified Capabilities

- `bot-config`: 新增日志级别配置需求，支持通过环境变量 `LOG_LEVEL` 控制应用日志级别，并规定 root logger 缺省 INFO。

## Impact

- **代码**：
  - `app/main.py`：`parse_config` 返回的 Namespace 新增 `log_level` 字段（解析 `LOG_LEVEL`，缺省 `INFO`）；新增级别解析纯函数（如 `resolve_log_level`）；重构 `setup_logger()`（root INFO、移除私有 handler、应用 logger 按解析结果设置级别、非法值 WARNING）；构造 `DingTalkStreamClient` 时传入 `logger=logger`。
  - `app/handlers/message.py`：消息入口新增 DEBUG 级回调头日志（topic、messageId），现有完整 raw_data 日志与之放在一起。
- **测试**：`tests/test_config.py` 增加 log_level 解析与级别回退用例；`tests/test_pipeline.py` 用 caplog 验证 DEBUG 下回调头与完整消息体均出现、INFO 下不出现。
- **依赖**：无新增第三方依赖，无配置破坏性变更（不设置 `LOG_LEVEL` 时应用业务日志保持 INFO 输出，仅消除重复打印与第三方 DEBUG 噪音）。
- **关联变更**：`support-group-chat-messages` 中原第 1 组日志任务与 bot-config、message-pipeline 中的日志需求整体迁入本变更；该变更后续真机验证依赖本变更先行合入。
