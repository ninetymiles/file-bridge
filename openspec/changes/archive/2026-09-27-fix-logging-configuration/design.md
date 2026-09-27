## Context

See proposal.md - Why。当前 `app/main.py` 的 `setup_logger()` 存在三处问题（自提交 7ee070c 引入后未再变动，git 全历史确认无已归档修复）：

1. `logging.basicConfig(level=logging.DEBUG)` 把 root logger 置为 DEBUG，未单独设置级别的第三方库 logger（`websockets`、`asyncio` 等）有效级别继承 root，DEBUG 帧收发日志持续刷屏。
2. `file-bridge` 应用 logger 被 `setLevel(INFO)` 钉死，消息入口 `app/handlers/message.py` 中已有的完整 raw_data DEBUG 日志永远沉默。
3. `file-bridge` logger 私有挂载了一个 StreamHandler 但保持默认 `propagate=True`：每条记录先由私有 handler 输出一次，再传播到 basicConfig 挂载的 root handler 输出一次，INFO 日志打印两遍。

另确认：`DingTalkStreamClient.__init__(self, credential, logger=None)` 支持注入应用 logger，当前 `app/main.py` 构造客户端时未传入；消息入口（`PipelineHandler._dispatch()`）现有 INFO 摘要日志与 raw_data DEBUG 日志各一行，但缺少 `callback.headers`（topic、messageId）日志。

## Goals / Non-Goals

**Goals:**

- 默认运行安静：INFO 级别下无第三方库 DEBUG 噪音、无应用 DEBUG 日志、无重复打印。
- 排障可观测：`LOG_LEVEL=DEBUG` 时单聊/群聊每条回调均可看到回调头（topic、messageId）与完整消息体 JSON（不截断、中文不转义）。
- 配置容错：非法 `LOG_LEVEL` 不阻止启动，回退 INFO 并告警。
- 不改变任何业务消息处理行为，仅改日志配置与诊断日志输出。

**Non-Goals:**

- 不改动 dingtalk-stream SDK 本体，不 pin/升级 `websockets` 或其他依赖版本。
- 不引入日志文件、日志轮转、结构化日志（JSON logging）或按模块细粒度级别配置。
- 不增加命令行参数（与 `OUTPUT_DIR` 等运行时配置一致，仅走环境变量）。
- 不涉及群聊 @ 前缀归一化与 richText 处理（留在 `support-group-chat-messages`）。

## Decisions

### 决策 1：root INFO 单点输出 + 应用 logger 级别可配，移除私有 handler

`setup_logger()` 重构为：

1. `logging.basicConfig(level=logging.INFO, format=<现有详细格式>)`：root logger 统一 INFO 与格式，成为唯一输出 handler。
2. 移除 `file-bridge` logger 的私有 StreamHandler，保持默认传播：应用记录经 root handler 单点输出，消除重复打印。
3. `file-bridge` logger 按解析结果 `setLevel`。Python 日志的级别过滤只在**发起记录的 logger** 上发生一次，向父 handler 传播时不再过滤：应用 logger 设为 DEBUG 时其 DEBUG 记录可见；`websockets` 等未设级别的第三方 logger 有效级别继承 root=INFO，DEBUG 帧继续被压制。两条需求因此同时成立，互不矛盾。

备选：保留私有 handler 并设 `propagate=False`。被否：双 handler 正是当前重复打印的根因；统一到 root 更简单，且在途变更 `integrate-fastapi-framework` 接入 Uvicorn 后日志体系也天然统一。

### 决策 2：级别解析为纯函数，非法值回退 INFO 并告警

新增纯函数（如 `resolve_log_level(raw: str) -> int`）：大小写不敏感映射 DEBUG/INFO/WARNING/ERROR；无法识别时返回 INFO。`parse_config` 返回的 Namespace 新增 `log_level` 字段，缺省读环境变量 `LOG_LEVEL`、缺省值 `"INFO"`，原样读入不做校验（校验是纯函数的职责，便于单测）。非法值时在 basicConfig 完成之后输出一条 WARNING（否则 root 尚未配置，告警自身可能丢失）。

### 决策 3：SDK 客户端注入应用 logger

`DingTalkStreamClient(credential, logger=logger)`：SDK 内部日志以 `file-bridge` 名义、统一格式输出，并随应用 logger 级别受控。已核对 SDK 0.24.3 构造器签名支持该参数。

### 决策 4：回调头与完整消息体在消息入口 DEBUG 级相邻输出

在消息入口（现 `_dispatch()`，归一化逻辑未来也落在此入口）的 INFO 摘要之外，DEBUG 级输出两行：回调头（topic、messageId，取自 `callback.headers`）与完整 `raw_data` JSON（沿用现有 `json.dumps(..., ensure_ascii=False, indent=2, default=str)`，不截断）。诊断日志放在任何消息内容改写之前，使群聊场景记录的是平台投递的原始字面量（含 `@机器人名` 前缀），供后续群聊变更真机核对。

## Risks / Trade-offs

- [`LOG_LEVEL=DEBUG` 时完整消息体进入日志，含 `sessionWebhook` 地址与 `downloadCode`] → 默认 INFO 不输出；DEBUG 仅排障时临时开启，敏感度与容器内本地日志等同；不在 README 中文档化该环境变量（用户决定），排障用法在变更记录与代码注释中保留。
- [默认不再看到 SDK/websockets DEBUG，改变既有排障习惯] → 这正是修复目的；需要时 `LOG_LEVEL=DEBUG` 可恢复应用侧可见性（第三方库仍受 root=INFO 约束，不随之刷屏）。
- [移除私有 handler 后，若测试或未来代码再次给 file-bridge 挂 handler 会重新双重打印] → 以单测/真机验证"同一条日志只输出一次"作为验收点；后续 FastAPI 接入统一走 root 配置。

## Migration Plan

1. 无数据迁移、无新增依赖；合入后重新构建镜像/重启即可生效。不设置 `LOG_LEVEL` 时行为差异仅为：不再重复打印、不再出现第三方 DEBUG 帧，业务 INFO 日志内容不变。
2. 回滚：还原代码即可；`LOG_LEVEL` 为可选环境变量，回滚后无残留配置影响。

## Open Questions

无。
