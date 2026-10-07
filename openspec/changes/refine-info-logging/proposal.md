## Why

生产环境以 INFO 级别运行，当前日志无法支撑日常运维排障：接收日志只有发送者与消息类型，看不到消息正文；机器人回复（含 storage-warmup 引入的"正在唤醒存储服务"提示）成功路径完全无日志，无法判断提示是否发出；下载阶段无开始标记，冷盘 35 秒等待期间日志一片空白；SDK 在 INFO 输出 `endpoint is {...}`（含 ticket）、`open connection, url=...`、`received disconnect ... message={整坨 JSON}` 等细节噪音，却没有明确的 Connected/Disconnected 结论行；`httpx` 对每个请求输出一行 INFO（含带签名参数的 OSS URL）；启动时不打印版本与生效配置，无法确认正在运行的是哪个版本、关联的是哪个机器人、各开关处于什么状态。

## What Changes

- **启动摘要**：`setup_logger` 之后、连接建立之前输出两条 INFO——版本号取环境变量 `APP_VERSION`（缺失或空时回退 `dev`），版本号由 CI 在构建镜像时从 git tag 解析并通过 Dockerfile ARG/ENV 注入；运行配置一行（`client_id` 明文、`log_level`、语义匹配开关及匹配器模式、单聊/群聊通知目标开关及已配置的 ID、`output_dir`）；`client_secret` MUST NOT 出现在日志中。同步清理 `pyproject.toml` 的 `[project]` 表，删除 `description`/`readme`，`version` 保留原值 `1.0.0` 加注释（uv/PEP 621 强制要求但运行时不读），使版本号唯一来源为 git tag。
- **接收消息正文提升到 INFO**：text 消息在接收摘要中附带正文；richText 附带与命令解析一致的合并文本（图片段渲染为 `<imgN>`，无文字时即 `content=<img1>`）。图片/文件/视频/audio 等类型不增加正文字段；downloadCode、回调头、原始 payload 等凭证与细节保持 DEBUG。
- **下载开始标记**：每个媒体文件进入下载阶段时输出一条 INFO（消息类型与原始文件名）；现有 `File saved:` INFO 保留不变；下载 URL、temp_path、字节数保持 DEBUG。
- **回复内容日志**：在唯一发送咽喉点 `async_reply_text` 输出 INFO，**先执行 DingTalk 发送、再记录日志**（成功 INFO、SDK 返回 None 时 WARNING），包含回复目标（单聊/群聊 + 发送者或群名）与完整回复文本，覆盖最终回复、唤醒提示、存储不可用提示、不支持类型兜底等全部出口。先 send 后日志是为了在冷盘窗口期不被本地日志 I/O 阻塞事件循环、延后面向用户的唤醒提示。
- **SDK 连接日志整形**：在应用日志配置中以 `logging.Filter` 对 SDK 经 `file-bridge` logger 输出的记录做整形（不修改第三方源码）：`received disconnect ...` 改写为结论行 `DingTalk stream disconnected: received disconnect message`（原始 JSON 不进 INFO）；`endpoint is ...` 改写为 `DingTalk stream connected.`；`open connection, url=...` 降级为 DEBUG；将 `httpx` logger 设为 WARNING，消除每请求一行的 INFO 噪音与签名 URL 暴露。
- **不做**：不改变 `LOG_LEVEL` 语义与日志格式；不引入 JSON 日志/追踪 ID；不修改 docker-compose.yml；不烘焙或打印 git commit、容器 ID；不新增第三方依赖。`APP_VERSION` 为新增环境变量（开发态可不配置，自动回退 `dev`）。

## Capabilities

### New Capabilities

- `runtime-logging`：服务运行期间的 INFO 级可观测性契约——启动版本与配置摘要、消息接收正文可见性、媒体下载与回复的关键事件日志、SDK 连接生命周期结论行、INFO 噪音与凭证信息边界。

### Modified Capabilities

无。消息处理、配置解析与日志级别的既有行为均不改变，本变更只新增日志输出并对既有第三方日志做呈现层整形。

## Impact

- **代码**：`app/main.py`（环境变量版本读取、启动摘要函数、日志 Filter 与 httpx 级别收敛，均挂在 `setup_logger`/`main` 接线中）；`app/handlers/message.py`（richText 合并逻辑抽为模块级函数、接收摘要附带正文、下载开始 INFO、`async_reply_text` 回复日志）。
- **构建**：`Dockerfile` 新增 `ARG APP_VERSION=dev` 与 `ENV APP_VERSION=$APP_VERSION`；`.github/workflows/docker-buildx.yml` 的 build-push 步骤增加 `build-args: APP_VERSION=${{ steps.meta.outputs.version }}`（该 workflow 已使用 `docker/metadata-action` 从 git tag 解析 semver，复用其输出）；`pyproject.toml` 的 `[project]` 表删除 `description`/`readme`，`version` 保留原值 `1.0.0`。
- **测试**：以 caplog 对启动摘要（含 `APP_VERSION` 已设/未设两条路径）、接收正文、下载/回复事件做契约测试；以合成 LogRecord 单测 Filter 的改写/降级规则；全量 general 集回归。
- **运行时**：INFO 日志将包含用户发送的消息正文与机器人回复文本（部署环境为用户自有 NAS/容器，需求方明确接受）；版本号在 CI 构建的镜像中等于 git tag 版本，本地与未传 build-arg 的构建回退 `dev`。
- **依赖、配置、数据库结构**：无新增第三方依赖；新增 `APP_VERSION` 环境变量（开发态可不配置）。
