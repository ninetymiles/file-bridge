## Context

容器 `output` 卷挂载在会休眠的 NAS 上，冷盘首次 I/O 的唤醒等待约 30 秒，阻塞发生在内核 syscall 内。磁盘写不只发生在下载与 SQLite 阶段——**接收日志本身就是每条消息的第一次磁盘写**：应用日志走 stderr，容器场景下经 Docker 日志驱动落宿主机盘；`logging` 的 `StreamHandler` 为同步 I/O，直接阻塞事件循环。

消息接收路径的完整磁盘访问时序为：

```
SDK ws 收包 -> route_message -> raw_process -> PipelineHandler.process()
  (此段 SDK 无任何日志输出，已核实 stream.py / handlers.py)
_dispatch:
  _log_received_message          ← INFO 接收摘要，首个同步磁盘写（stderr -> Docker 日志驱动）
  handlers:
    CommandHandler               ← 命中时 logger.info("Command matched")、命令回调内日志
    MediaFileHandler             ← makedirs(.tmp) / 下载写盘 / SQLite / 读回抽 EXIF
  Dispatcher 发送最终回复         ← reply_text 为纯 requests.post，发送前无日志
```

关键约束：日志写在协程内同步执行，会把整个事件循环线程占住约 30 秒；此时即便已启动 `asyncio.sleep(3)` 计时器，到期回调也无法被调度——提示会在磁盘唤醒后才发出，失去意义。因此预热必须以"探针进线程 + 计时器留事件循环 + 首条日志在预热完成后才输出"的结构组织。

## Goals / Non-Goals

**Goals:**

- 冷盘时任意消息在 3 秒无响应内向发送者发出固定唤醒提示；热盘零感知（无多余消息，耗时增加可忽略）。
- 唤醒等待不阻塞事件循环。
- 预热只设一个接线点（消息处理入口），文件消息、"重建索引"命令及所有其他消息均被传递性覆盖。
- 机制收敛为一个无业务状态的公共模块，探针与提示回调注入。
- 不新增依赖、不新增配置项、不改变最终回复的裁决规则。

**Non-Goals:**

- 不处理启动期冷唤醒（`init_db` / `rebuild_index` 在事件循环启动前执行，上线通知迟到问题另议）。
- 不做跨消息的并发唤醒去重（single-flight）：冷盘瞬间多条消息各发一条提示的概率极低。
- 不改变 shutdown drain 语义；不清理 `.activity` 文件；不调整日志级别或日志驱动。

## Decisions

### 决策 1：单函数模块，探针与回调均注入

新增 `app/services/disk_warmup.py`，只暴露一个协程：

```python
async def ensure_storage_ready(probe, on_waking, delay=3.0) -> None
```

- `probe`：零参数同步可调用对象，内部完成 `.activity` 写入与 fsync；模块用 `asyncio.to_thread(probe)` 执行。
- `on_waking`：零参数异步可调用对象，超时时由业务侧发送提示；模块不 import 钉钉相关代码，保持可独立单测（测试以 `asyncio.sleep` 假探针驱动快/慢/异常三条路径）。
- `delay` 默认 3.0 秒，代码常量，不进环境变量。

### 决策 2：两 task + FIRST_COMPLETED 竞争，不用 wait_for

```
probe_task = create_task(to_thread(probe))
timer_task = create_task(sleep(delay))
finished, _ = await wait({probe_task, timer_task}, return_when=FIRST_COMPLETED)

probe 先完成:  cancel(timer_task)，静默返回
timer 先到期:  await on_waking()；随后 await probe_task（等完剩余唤醒时间）
共同路径:      await probe_task；探针异常原样抛出
```

不能用 `wait_for(probe, timeout=3)`：超时会取消被等待对象，而 `to_thread` 无法取消底层线程，会导致探针仍在运行、结果被丢弃且异常成为 "never retrieved"。独立 timer_task 在两条路径下都有明确归宿（被取消或自然完成）。

### 决策 3：探针必须是写 + fsync，不能是 exists 检查

`os.path.exists(output_dir)` 走路径解析，挂载根目录 dentry 长期留在内核与 SMB/NFS 客户端缓存中，冷盘时可能直接缓存命中返回成功，磁盘并未被唤醒——真正的写盘时依旧卡死，预热形同虚设。覆写 `.activity` 产生到达 NAS 服务端的 CREATE/写请求，`flush()` 后再 `os.fsync()` 将"磁盘就绪"确定地关在探针内。`.activity` 每次覆写为当前时间戳，单文件、无清理逻辑。

### 决策 4：唯一接线点在 `_dispatch` 入口，且首条日志必须排在预热之后

```
_dispatch:
    raw_data / incoming_message 解析
    await ensure_storage_ready(               ← 新增
        probe=activity_probe,                  # output/.activity 写 + fsync
        on_waking=lambda: async_reply_text(WAKING_STORAGE_TEXT, incoming_message),
    )
    except ProbeError → logger.error + reply_text(STORAGE_UNAVAILABLE_TEXT) + return
    _log_received_message                     ← 现有首条 INFO 日志，位置在预热之后
    handler chain ...                         ← 现有处理链，不动
```

理由：SDK 从收包到调用 `process()` 之间无任何日志（已核实 `stream.py` 与 `handlers.py` 的 callback 分支），因此应用内首个同步磁盘写就是 `_log_received_message` 的 INFO 摘要。预热 await 在该日志之前完成，才能保证计时器回调能被事件循环调度——若先打日志再预热，同步 stderr 写会把事件循环卡死约 30 秒，计时器到期也无法执行。接线点只有一个，处理链与处理器实现均无需感知预热存在。

### 决策 5：预热覆盖所有消息类型，不按类型区分

接收日志是每条消息不可回避的磁盘写，因此 `text`、`audio` 等"不碰 output 卷"的消息同样会在冷盘时被首条日志阻塞。预热在入口对所有消息执行一次，取消此前"只在碰盘动作前预热"的区分；文件消息与"重建索引"命令的下游磁盘访问被入口预热传递性覆盖，无需在 `MediaFileHandler` 或命令回调中重复接线。这同时意味着 `CommandAction` 签名不变，命令回调无需获取 pipeline 上下文。

### 决策 6：提示由 Dispatcher 直发，不引入意图模型的例外

唤醒提示与存储不可用提示都在处理链之外由 Dispatcher（`_dispatch` 内）直接调用 `async_reply_text` 发送，不构造 `ReplyIntent`、不参与层级裁决。"处理器不自行发送回复"的既有规则保持不变——提示的发送方是 Dispatcher 而非处理器，意图模型不需要为此开任何例外。发送路径经 `to_thread(reply_text)`，`reply_text` 为纯 `requests.post`、发送前无日志（已核实 SDK），冷盘时提示能准点发出。

### 决策 7：探针异常处置为"回复不可用提示并终止该消息"

探针抛异常（存储卷不可达、权限不足等）时，在 `_dispatch` 捕获：记录一条 ERROR 日志（此时 stderr 写也可能阻塞，但属于故障态可接受）、调用 `reply_text` 发送固定措辞的存储不可用提示、正常返回 ACK。消息不再进入处理链。异常不向 SDK 传播，避免被 SDK 的 `background_task` 兜底打一条缺少上下文的 error 日志。

## Risks / Trade-offs

- **每条消息多一次 fsync**：热盘下为亚毫秒级，且探针只写一个极小的 `.activity` 文件，可接受。
- **并发消息重复提示**：冷盘瞬间到达 N 条消息会产生 N 条唤醒提示。已按 Non-Goals 接受；未来如有投诉再引入 single-flight（共享一个探针 future + 仅首个调用方挂回调），模块形态不需要推翻。
- **shutdown 期间探针线程不可取消**：与现有 SQLite `to_thread` 调用语义一致，由 `drain_active_tasks` 的 10 秒上限兜底；极端情况下探针随进程退出终止，`.activity` 为覆写文件无一致性问题。
- **预热故障态下 ERROR 日志可能阻塞**：探针失败说明存储已异常，此时 stderr 写再阻塞属于故障放大，已接受；恢复后自愈。
- **NAS 语义差异**：fsync 对不同网络文件系统的刷盘语义有差异，但 CREATE+写+fsync 已足以触发服务端磁盘唤醒，不依赖特定 NAS 的缓存一致性保证。
