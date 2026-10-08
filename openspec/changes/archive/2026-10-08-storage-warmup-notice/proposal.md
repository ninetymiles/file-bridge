## Why

生产环境中容器部署在会休眠的 NAS 上，冷盘唤醒约需 30 秒，阻塞发生在磁盘访问的同步 syscall 内。除文件下载落盘与 SQLite 访问外，**消息接收路径上的第一条 INFO 接收日志本身就是磁盘写**（stderr 经 Docker 日志驱动落宿主机盘，`logging` 为同步 I/O，直接阻塞事件循环），因此冷盘时任意消息（含纯文本）都会无反馈卡住约 30 秒，用户无法区分"服务卡死"与"正在唤醒存储"。本变更在消息处理入口引入统一的存储预热与超时提示机制：3 秒内磁盘就绪则静默继续，超过 3 秒则先回复一条"正在唤醒存储服务"的提示，磁盘就绪后再进入日志输出与处理链，最终结果回复按现有链路发送。

## What Changes

- **新增公共预热模块** `app/services/disk_warmup.py`：提供 `ensure_storage_ready(probe, on_waking, delay=3.0)` 协程。探针通过 `asyncio.to_thread` 在线程中执行以避免阻塞事件循环，并与 `asyncio.sleep(delay)` 计时器竞争：探针先完成则取消计时器、静默继续；计时器先到期则执行业务注入的 `on_waking` 回调发送提示，随后继续等待探针完成；探针异常向调用方传播。模块不含任何钉钉业务逻辑，探针与提示回调均由调用方注入。
- **探针采用确定性写操作**：向 `OUTPUT_DIR/.activity` 覆写当前时间戳并 `flush()` + `fsync()`，确保写请求到达 NAS 服务端、真正触发唤醒；不使用 `os.path.exists` 这类可能命中目录项缓存、冷盘时假返回的探测方式。
- **唯一接线点：`PipelineHandler._dispatch` 入口**：在解析消息之后、输出第一条接收日志（`_log_received_message`）之前，`await` 完成预热竞争。预热完成后，该消息的日志输出、下载落盘、SQLite 访问、命令执行全部在已唤醒的磁盘上进行。经核实，SDK 从收包到调用 `process()` 之间无任何日志，应用内首个同步磁盘写即该接收日志，故入口预热覆盖一切下游磁盘访问。
- **覆盖范围为所有收到的消息**：接收日志是每条消息不可回避的磁盘写，因此不再按消息类型区分是否预热。文件消息的下载/落盘/SQLite 与"重建索引"命令的索引核验均被入口预热传递性覆盖，无需在 `MediaFileHandler` 或命令回调内各自接线；`CommandAction` 签名不变。
- **唤醒提示由 Dispatcher 直发**：提示经 `pipeline.async_reply_text` 发送（纯 HTTP、发送路径无磁盘写），不构造回复意图、不参与意图层级裁决；处理器"不自行发送回复"的既有规则不变。
- **探针异常处置**：预热探针抛异常（存储卷不可达等）时，Dispatcher 记录 ERROR 日志并向发送者回复一条固定措辞的存储不可用提示，该消息不再进入处理链。
- **文案与阈值固化**：唤醒提示与存储不可用提示的措辞固定在代码中，3 秒阈值为模块默认参数，均不引入配置项。

明确不做：启动期冷唤醒（上线通知迟到）不在本变更范围；不做跨消息的并发唤醒去重（single-flight）；不改动处理器、意图裁决、shutdown drain 的既有语义；不新增第三方依赖；不清理 `.activity` 文件。

## Capabilities

### New Capabilities

- `storage-warmup`：消息处理入口的存储预热与超时提示机制，涵盖探针形式（同步写 + fsync、经线程执行）、预热必须先于首条日志输出的时序约束、3 秒竞争规则、提示回调注入、探针异常处置、覆盖全部消息类型等通用行为约束。

### Modified Capabilities

- `message-pipeline`：修改 "Pipeline 流转模型" 要求——Dispatcher 在启动处理链之前先执行存储预热（由 `storage-warmup` 能力定义），预热超时的唤醒提示与探针异常的存储不可用提示由 Dispatcher 直接发送，均不属于回复意图、不参与层级裁决、不影响后续意图汇总与兜底规则。

## Impact

- **代码**：新增 `app/services/disk_warmup.py`；`app/handlers/message.py`（`_dispatch` 入口接线、提示文案常量、`PipelineHandler` 构造注入预热探针）；`app/main.py`（装配处绑定 `output_dir` 的 `.activity` 探针）。`MediaFileHandler`、`CommandHandler`、命令回调、下载器均无需改动。
- **运行时产物**：`OUTPUT_DIR/.activity` 活动文件（反复覆写，单文件，不清理）。
- **依赖、配置、数据库结构**：无变更；不新增环境变量。
- **测试**：以假探针（可控延迟/异常）单测预热模块的快速返回、超时提示、探针异常三条路径；组合测试验证：慢探针下唤醒提示先于一切日志与最终回复、快探针下无任何额外消息、探针异常回复存储不可用、各消息类型（text/picture/file/richText/audio）均先经预热、"重建索引"命令冷盘先收唤醒提示再收结果；验证 shutdown drain 语义不变。
