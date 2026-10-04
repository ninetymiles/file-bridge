## Why

生产环境中容器的 `output` 卷部署在会休眠的 NAS 上，冷盘唤醒约需 30 秒，阻塞发生在首次磁盘访问的同步 syscall 内。当前文件消息链路（下载临时文件）与"重建索引"命令在冷盘期间会长时间无任何反馈，用户无法区分"服务卡死"与"正在唤醒存储"。本变更在确定要访问磁盘的动作前引入统一的预热探测与超时提示机制：3 秒内磁盘就绪则静默继续，超过 3 秒则先回复一条"正在唤醒存储服务"的提示，最终结果回复仍按现有链路发送。

## What Changes

- **新增公共预热模块** `app/services/disk_warmup.py`：提供 `ensure_storage_ready(probe, on_waking, delay=3.0)` 协程。探针通过 `asyncio.to_thread` 在线程中执行以避免阻塞事件循环，并与 `asyncio.sleep(delay)` 计时器竞争：探针先完成则取消计时器、静默继续；计时器先到期则执行业务注入的 `on_waking` 回调发送提示，随后继续等待探针完成；探针抛出的异常照常向调用方传播。模块不包含任何钉钉业务逻辑，探针与提示回调均由调用方注入。
- **探针采用确定性写操作**：向 `OUTPUT_DIR/.activity` 写入当前时间戳并 `flush()` + `fsync()`，确保一次必然到达 NAS 服务端的 CREATE/写请求真正触发唤醒；不使用 `os.path.exists(output_dir)` 这类可能命中目录项缓存、冷盘时假返回的探测方式。
- **文件消息链路接线**：`MediaFileHandler` 在确定要碰盘之后、下载开始之前调用一次预热——单条 `picture`/`video`/`file` 消息在 `_process_one_image` 之前；`richText` 消息在图片循环之前（整条消息仅预热一次，多图不重复提示）。不碰盘的消息（文本、语音、无图片段的 richText 等）不预热。
- **"重建索引"命令接线**：`main.py` 的 `rebuild_index` 命令回调在执行 `async_rebuild_index()` 前执行同一预热；为此 `CommandAction` 签名扩展第三个参数 `pipeline`，由 `CommandHandler` 透传，命令回调借此发送中间态提示。
- **中间态提示的措辞固化**：文案固定在代码中（如"正在唤醒存储服务，请稍候…"），不引入配置项；3 秒阈值为模块默认参数，不做环境变量配置。

明确不做：启动期冷唤醒（上线通知迟到）不在本变更范围；不做跨消息的并发唤醒去重（single-flight）；预热不与下载 URL 解析的 HTTP 请求并发；不新增第三方依赖。

## Capabilities

### New Capabilities

- `storage-warmup`：磁盘访问前的预热探测与超时提示机制，涵盖探针形式（同步写 + fsync、经线程执行）、3 秒竞争规则、提示回调注入、异常传播、仅在确定碰盘的动作前触发等通用行为约束。

### Modified Capabilities

- `message-pipeline`："Pipeline 流转模型" 增加一个受控例外——处理器在处理过程中可经 `pipeline` 发送中间态进度提示（当前唯一用途为存储唤醒提示），该提示独立于最终 `ReplyIntent` 回复，不改变意图汇总与裁决规则；`CommandAction` 回调签名扩展为接收 `pipeline` 参数。
- `file-indexing`：修改"'重建索引'维护指令"要求，新增冷盘唤醒提示场景——重建开始前执行存储预热，超 3 秒先回复唤醒提示，完成后仍回复既有结果文案。

## Impact

- **代码**：新增 `app/services/disk_warmup.py`；`app/handlers/message.py`（`MediaFileHandler` 两处接线、`CommandAction` 类型与 `CommandHandler` 调用处透传 `pipeline`、提示文案常量）；`app/main.py`（`rebuild_index` 闭包接线，构造注入 `output_dir` 对应的探针）；`app/services/file_downloader.py` 无需改动（首次碰盘点由预热前置承担）。
- **运行时产物**：`OUTPUT_DIR/.activity` 活动文件（反复覆写，单文件，不清理）。
- **依赖、配置、数据库结构**：无变更；不新增环境变量。
- **测试**：以假探针（可控延迟/异常）单测模块的快速返回、超时提示、探针异常三条路径；模块组合测试验证文件消息与重建索引命令在慢探针下先收到唤醒提示、再收到最终回复，快探针下只有最终回复；验证不碰盘消息不产生 `.activity` 写入。
