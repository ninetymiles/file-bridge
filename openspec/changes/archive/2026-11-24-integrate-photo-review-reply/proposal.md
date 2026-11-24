# Proposal

## Why

照片落盘后的回复目前只有文件名与 EXIF 摘要行，用户拿到的是"参数"而不是"评价"。`photo-review` 服务与 CLI 已经可用并经过真实网关验证，但它还没有接入消息链路——HTTP 响应上没有任何一处会带上点评。把点评接进钉钉回调链后，用户发照片就能直接收到一段 AI 点评；未配置网关或点评失败时，回复必须与今天完全一致。

## What Changes

- **接入点**：在 `app/handlers/message.py` 的 `MediaFileHandler` 中接入 `PhotoReviewer`，覆盖单聊 `picture` 与群聊 `richText` 图片段两条路径；`video`、`file` 不点评。FastAPI 与运行形态无关，本次改动在钉钉 handler 上完成。
- **可选配置**：新增 `ReviewConfig.from_env_optional(env) -> ReviewConfig | None`。三个 `OPENAI_*` 全部存在才构造点评器；任一缺失时点评能力静默禁用，回复保持现状（现有 `from_env()` 对 CLI 的"缺失即报错"语义不变）。
- **启动可用性探测**：服务启动时以 `GET <base>/models/<urlencoded model>`（3 秒超时）验证网关与模型名；成功记 INFO，失败记 WARNING 并**硬禁用**本次进程内的点评能力。
- **两段式回复**：第一次回复始终是"保存成功 + EXIF"。点评在 15 秒合并窗口内返回时并入这一条（不加前缀）；窗口到期才发送第一条，点评继续运行，拿到后再补发一条以「照片点评：」开头的消息。**最差 2 条消息，不产生中间提示。**
- **请求上限**：点评请求的总墙钟上限为 60 秒（`asyncio.wait_for`，包住整批 gather），到点取消请求、回收连接与任务、记 WARNING 且不再补发。连接超时单独设为 5 秒。CLI 保持无总超时。
- **群聊多图合并**：同一批图片的全部点评合并为一条消息，按「图1：…」「图2：…」分段，只包含成功的图片；失败图片静默省略，不写"点评失败"。
- **关停语义**：第二条消息发生在 ACK 之后，点评任务不注册进 `_active_tasks`；停机瞬间未完成的点评直接丢弃并记日志，不为娱乐功能增加生命周期管理。

**非目标（Non-goals）**

- 不做点评缓存、流式输出、打分持久化，也不把点评写进 SQLite。
- 不引入图片预热或启动时主动加载模型；探测只验证地址与模型名，不触发推理。
- 不改动 CLI 的参数、输出与退出码，也不给 `reasoning_effort` 增加环境变量。
- 不做 FastAPI 集成（由 `integrate-fastapi-framework` 另行负责）。

## Capabilities

### New Capabilities

（无。点评能力已由 `photo-review` 与 `photo-review-cli` 定义，本次只扩展其需求。）

### Modified Capabilities

- `photo-review`: 新增"可选配置解析""启动可用性探测""调用方请求上限"三项需求，明确服务在消息链路中的启用/禁用与超时边界。
- `message-pipeline`: 修改单媒体回复与 richText 逐张处理两条既有需求，允许在 EXIF 之后追加点评，并新增"照片点评两段式回复"需求定义合并窗口、补发前缀与失败静默语义。

## Impact

- 代码：`app/services/photo_review.py`（可选配置、探测辅助）、`app/handlers/message.py`（`_ImageProcessResult`、`_process_one_image`、`_handle_media`、`_handle_rich_text`、两段式发送）、`app/main.py`（装配与探测调用）。
- 配置：沿用 `.env` 中已有的 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`；无新增变量，缺失即禁用。
- 依赖：无新增；`httpx` 与 Pillow 已在依赖中。
- 系统：点评依赖可访问的 OpenAI 兼容 vision 网关。网关不可用、模型名错误或响应超时都只影响点评，不影响落盘、索引与 EXIF 回复。
- 测试：新增可控延迟的假点评器与 `httpx.MockTransport` 用例，不连真实网关、不读写进程环境变量。
