## Context

现状代码事实（已核实）：

- 日志配置集中在 `app/main.py` 的 `setup_logger()`：`basicConfig` 给 root 挂一个 StreamHandler（级别 INFO），应用 logger `file-bridge` 按 `LOG_LEVEL` 调级；SDK 客户端在 `main()` 中以 `logger=logger` 显式注入该 logger，因此 `stream.py` 的连接日志记录器名就是 `file-bridge`（生产 CSV 已证实）。
- SDK 三条 INFO 连接日志位置：`stream.py:149` open connection URL、`stream.py:71` endpoint dict（含 ticket）、`stream.py:119` disconnect 原始 JSON。`start()` 的成功路径上没有专门的"已连接"日志，`endpoint is` 是 ws 建立前最后一条成功记录；其后失败会走 ERROR 并重试。
- 回复统一走 `PipelineHandler.async_reply_text → to_thread(reply_text)`，是所有回复出口的唯一咽喉点；SDK `reply_text` 成功零日志、失败时自身打 ERROR 并返回 None。
- richText 合并逻辑目前是 `CommandHandler._merge_rich_text` 静态方法，返回 `(合并文本, 是否含图)`，命令解析与日志想要的正文形态完全一致。
- 版本获取路径：项目 `[tool.uv] package = false`，`importlib.metadata.version("file-bridge")` 不可用；运行时需一个与发布镜像 tag 一致、本地可默认、不依赖 git 的版本来源。CI workflow `.github/workflows/docker-buildx.yml` 已使用 `docker/metadata-action@v6` 的 `type=semver,pattern={{version}}` 从 git tag 解析出版本（`steps.meta.outputs.version`）。当前 `pyproject.toml` 的 `[project]` 表中 `version`、`description`、`readme` 是 `uv init` 模板遗留的发行元数据，在 `package=false` 下无人读取（只有 `name`、`dependencies`、`requires-python` 被 uv 实际使用），将一并清理，使版本号的唯一来源为 git tag → `APP_VERSION`。需求方明确不打印 commit/image/container。

## Goals / Non-Goals

**Goals:**

- INFO 级别形成完整的单消息追踪链：接收（含正文）→ 下载开始 → 保存成功（已有）→ 回复（含文本）。
- 启动即可在 INFO 读出：版本、关联的 client_id、日志级别、语义匹配模式、两类通知目标开关与 ID、输出目录。
- 连接生命周期在 INFO 只剩结论行；过程细节与第三方请求行退出 INFO。
- 凭证（secret、token、downloadCode、签名 URL）维持 INFO 不可见。

**Non-Goals:**

- 不改日志格式（LOG_FORMAT）、不改 LOG_LEVEL 语义、不引入结构化/JSON 日志与请求追踪 ID。
- 不修改 dingtalk_stream 第三方源码、不做 vendor fork。
- 不修改 docker-compose.yml；不烘焙 git commit 或容器 ID 到镜像。
- 不调整 media_metadata、命令匹配分数等既有 DEBUG 诊断内容。

## Decisions

### 决策 1：版本由 CI 从 git tag 注入 ENV，运行时取 `APP_VERSION`（缺省 `dev`）

版本号的唯一事实来源是 git tag，与发布镜像 tag 永远一致，避免 pyproject 字段与实际发布版本漂移。链路：

1. CI（`.github/workflows/docker-buildx.yml`）已通过 `docker/metadata-action` 解析 `type=semver,pattern={{version}}`，在 build-push 步骤增加 `build-args: APP_VERSION=${{ steps.meta.outputs.version }}`。
2. `Dockerfile` 增加 `ARG APP_VERSION=dev` 与 `ENV APP_VERSION=$APP_VERSION`，将构建参数固化为容器运行时环境变量；未传 build-arg 的本地构建自动取 `dev`。
3. 运行时 `get_app_version() -> str`：`os.getenv("APP_VERSION") or "dev"`——用 `or` 而非默认值，处理 ENV 被设为空串的边界（分支 push 时 `meta.outputs.version` 可能为空）。
4. 同步清理 `pyproject.toml` 的 `[project]` 表：删除 `description`、`readme`；`version` 保留原值 `1.0.0` 并加注释——uv/PEP 621 在 `[project]` 存在时强制要求 `version`（或 `dynamic`，但 `dynamic` 会触发构建后端而 package=false 下 setuptools 扁平布局构建失败）。由于 `package=false` 下该字段运行时从不被读取，保留原值不构成版本漂移；真实版本唯一来源仍是 git tag → `APP_VERSION`。

- 否决 `importlib.metadata`：package=false 时发行版不安装，本地与容器均取不到（已实测）。
- 否决 `tomllib` 读 pyproject：版本号需手动同步 pyproject，存在"镜像 tag 是 1.2.0 但日志打印 1.0.0"的漂移风险；ENV 方案让 tag 即版本，零漂移。
- 否决构建期写 `_version.py`：会引入构建产物文件与构建步骤复杂度，ENV 是更直接的运行时通道。

### 决策 2：启动摘要为独立函数，两条 INFO

`log_startup_summary(config, logger)`，在 `main()` 中 `setup_logger` 之后、Credential/索引检查之前调用：

```
INFO  File Bridge starting: version=<APP_VERSION 或 dev>
INFO  Configuration: client_id=<id>, log_level=<LEVEL>, semantic_command=<on|off (substring)>,
      notify_staff=<on (staff=<id>)|off>, notify_group=<on (conversation=<id>)|off>, output_dir=<dir>
```

抽函数而非内联在 `main()`，沿用"含业务逻辑的启动步骤独立可测、main() 保持朴素接线"的既有约定。client_id 明文（需求方用于核对关联机器人，非机密）；client_secret 不读取进摘要。

### 决策 3：richText 合并逻辑提为 message.py 模块级函数，单一实现两处复用

新增模块级 `merge_rich_text_segments(segments) -> tuple[str, bool]`，`CommandHandler._merge_rich_text` 保留为薄委托静态方法（现有 4 个单测与内部调用零改动），`_log_received_message` 直接调用模块级函数生成 INFO 正文。

- 否决 PipelineHandler 反向调用 `CommandHandler._merge_rich_text`：层级倒挂，日志依赖具体处理器。
- 否决新建 util 文件：单函数拆分未达临界，遵循单文件优先。

### 决策 4：正文并入既有接收摘要行，不新增日志行；类型化 DEBUG 去重

接收摘要仍是每条消息一行，text/richText 追加 `, content=<正文>`：

- `text`：直接取 content 字段。
- `richText`：用决策 3 的合并文本（无文字时即 `content=<img1>`，已与需求方确认）。
- 删除 `Text content: ...` 这条 text 专用 DEBUG（信息已进 INFO）；richText 的逐段 DEBUG 中，文本段不再重复打印，图片段/其他段的 downloadCode 明细保留 DEBUG；raw payload 与回调头 DEBUG 保留——凭证与完整报文在 DEBUG 仍可全量排障。

图片/文件/视频摘要现状已含 filename（适用时），不增加虚构字段。

### 决策 5：下载开始 INFO 放在 `_process_one_image` 下载任务之前

```
INFO  Downloading file: type=<msgtype>, name=<original_filename>
```

每个媒体文件处理恰好一次（richText 多图自然逐条产生），位于创建 download_task 之前，冷盘阻塞期间日志不再空白。严格不带 code/URL/token，保持 `test_resolve_url_info_level_hides_codes_and_url` 契约；URL 解析、流式完成明细维持 DEBUG。

### 决策 6：回复日志挂在 async_reply_text 唯一咽喉点，且**先 send 后日志**

先执行 DingTalk 发送（`to_thread(reply_text)`，纯网络 I/O 不碰本地磁盘），再根据结果输出日志：成功 INFO，SDK 返回 None 则 WARNING：

```
INFO  Replied to <private|group> (<发送者昵称|群名>): <完整回复文本>
WARN  Reply failed to <目标>: <完整回复文本>
```

**为何先 send 后日志（而非先日志后 send）**：唤醒提示（`on_waking`）与存储不可用提示在 `ensure_storage_ready` 内部发送，此刻 probe 尚未完成、磁盘仍可能处于冷盘状态。若先 `logger.info()`（同步写本地日志，可能触发冷盘 I/O 阻塞事件循环），会延后 DingTalk 网络发送，抵消 warmup-notice"3s 内告知用户"的设计意图。先 send 再日志使面向用户的提示不受本地日志 I/O 拖累；此时 probe 多半已完成或接近完成，日志写在热盘窗口期。

目标类型与名称从 `incoming_message` 的 conversation_type / sender_nick / conversation_title 取（与接收摘要同源）。该点天然覆盖最终合并回复、唤醒提示、不可用提示、不支持类型兜底全部出口，处理器与预热模块无需感知日志。多行回复文本原样输出（运维读日志文件，不需要压平）。

### 决策 7：SDK 日志用 logging.Filter 呈现层整形，挂到 root handler

在 `setup_logger()` 内新增一个 filter（类定义放 main.py），挂到 root 的 StreamHandler（handler 级 filter 对传播来的记录同样生效，规避 logger 级 filter 只作用于始发 logger 的陷阱）。仅对 `record.name == "file-bridge"` 且 `record.filename == "stream.py"` 的记录按消息前缀整形：

| 前缀（当前 SDK 版本） | 动作 |
|---|---|
| `received disconnect topic=disconnect` | 改写 msg 为 `DingTalk stream disconnected: received disconnect message`（保持 INFO，剥离整坨 JSON） |
| `endpoint is ` | 改写 msg 为 `DingTalk stream connected.`（剥离 endpoint dict 与 ticket） |
| `open connection, url=` | levelno/levelname 改为 DEBUG（root handler 级别为 0，降级后仍会由 handler 输出；记录在始发处已是 INFO，不经过 logger 级二次过滤） |
| 其他 | 原样放行（含 `[start] network exception` ERROR 与 unknown topic WARNING） |

- 匹配用文件名 + 消息前缀，不用行号：SDK 小版本升级行号漂移不影响，措辞变更时表现为"原始行重新出现"的纯外观退化，单测用合成 LogRecord 锁定当前措辞，升级 SDK 时测试会直接提醒。
- 否决改 SDK 源码/vendor fork：第三方维护负担与升级成本过高。
- 否决在应用侧包一层 SDK client 子类：SDK 的日志分散在 start()/route_message()，包装无法覆盖。
- 顺带在 `setup_logger()` 将 `logging.getLogger("httpx").setLevel(WARNING)`：消除逐请求 INFO（含签名 URL）；DEBUG 级别下如需 HTTP 细节由既有 DEBUG 诊断覆盖（httpx 不随 file-bridge 调级是有意的：它是第三方噪音源）。

### 决策 8：存储预热必须先于消息处理链所有 INFO 日志（不变量）

`_dispatch` 的第一个操作是 `ensure_storage_ready`，其内部同步创建 3s 唤醒定时器与磁盘探针（worker 线程）。此后消息链上所有可能触发本地磁盘 I/O 的 INFO 日志（接收摘要、下载开始、回复）均位于预热完成之后。此顺序是冷盘场景的生命线：若任何 INFO 日志先于预热，其同步磁盘写会阻塞事件循环，导致唤醒定时器无法在 3s 内触发、预热提示失效。

- 唤醒提示回复是唯一例外：它在 `ensure_storage_ready` 的 `on_waking` 回调内发出，此时探针未完成、磁盘仍冷；因此该回复必须"先 DingTalk 发送、后本地日志"（见决策 6），使面向用户的提示不受本地日志 I/O 拖累。
- 此不变量对未来修改构成硬约束：在 `_dispatch` 链路新增任何 INFO 日志时，MUST 确认其位于 `ensure_storage_ready` 调用之后；若该日志属于唤醒提示本身，MUST 保证发送先于日志。

### 决策 9：测试策略

- 启动摘要：caplog 契约测试覆盖全字段 on/off、client_id 可见、secret 不出现；版本函数 `get_app_version` 单测覆盖两条路径——`APP_VERSION` 已设（含空串）时返回原值或回退 `dev`，未设时返回 `dev`；断言不读取任何文件。
- 消息链：caplog 断言 text/richText（含纯图片 richText）正文在 INFO；Downloading 行数量与类型；Replying 行覆盖普通回复与唤醒/失败路径（失败用 reply_text 返回 None 驱动，不断言 SDK 自身日志）。
- **预热时序**：以 mock 断言 `_dispatch` 中 `ensure_storage_ready` 的调用先于第一条 INFO 日志（`_log_received_message` 摘要）；唤醒提示路径下 `reply_text` 调用先于 `logger.info` 调用。此测试锁定决策 8 的不变量，防止未来重构时被无意破坏。
- Filter：合成 LogRecord 直接喂 filter，断言改写文本、级别变更与无关记录放行三条规则。
- 组合测试（test_integration）补充对新 INFO 行的契约断言，不改变既有回复断言。

## Risks / Trade-offs

- **INFO 日志含用户消息正文与回复文本** → 需求方明确接受：部署在用户自有 NAS/容器，日志文件不离开自有环境；凭证类信息仍严格排除。群聊 @ 后的原文同样会入日志。
- **Filter 与 SDK 日志措辞耦合** → 前缀+文件名匹配、单测锁定；措辞漂移最坏结果是原始噪音行重现，不影响功能。
- **降级记录依赖 handler 级别为 0** → 项目仅 basicConfig 单 handler，部署形态固定；若未来有人把 root handler 级别提到 INFO 以上，open connection 行会直接消失（可接受的排障细节损失），不产生异常。
- **`APP_VERSION` 未注入**（本地构建或分支 push）→ 版本显示 `dev`，CI 正式镜像（tag 触发）才显示真实版本号；这是有意设计，本地与非 tag 构建本就不应冒充发布版本。

## Migration Plan

1. 合并代码后重新构建镜像并部署（注意：storage-warmup-notice 也需随本次镜像一并上线——生产当前镜像仍缺预热逻辑）。
2. 部署后核对：启动两条摘要行；发一条文本与一条图文 richText 确认 INFO 正文；冷盘场景确认唤醒提示有对应 Replying 行；断线重连时只见 Connected/Disconnected 结论行、无 httpx 请求行。
3. 回滚：重新部署旧镜像，无数据/配置/依赖迁移。
