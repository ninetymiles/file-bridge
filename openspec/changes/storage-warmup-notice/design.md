## Context

容器 `output` 卷挂载在会休眠的 NAS 上，冷盘首次 I/O 的唤醒等待约 30 秒，阻塞发生在内核 syscall 内。文件消息链路当前的磁盘访问时序为：

```
get_download_url (HTTP，不碰盘)
  -> download_file_stream:
       os.makedirs(.tmp)          ← 首次碰 NAS，同步调用，在协程内
       open() / f.write() × N
  -> is_duplicate (SQLite + os.path.exists，已包 to_thread)
  -> save_file (makedirs + shutil.move，同步)
  -> insert_record (SQLite，已包 to_thread)
  -> extract_media_metadata (读回文件，同步)
```

"重建索引"命令则在 `async_rebuild_index()`（已包 `to_thread`）中全表扫描并逐条 `os.path.exists`。

关键约束：最早的碰盘点 `os.makedirs` 是协程中的同步调用。冷盘时它会占住事件循环线程，此时即便启动 `asyncio.sleep(3)` 计时器，到期回调也无法被调度——提示会在约 30 秒后磁盘唤醒时才发出，失去意义。因此"预热 + 计时"必须把阻塞式磁盘访问放进工作线程，两者才能真正竞争。

## Goals / Non-Goals

**Goals:**

- 冷盘场景下，文件消息与"重建索引"命令在 3 秒无响应时向发送者发送固定唤醒提示；热盘零感知（无多余消息、耗时增加可忽略）。
- 唤醒等待不阻塞事件循环。
- 机制收敛为一个无业务状态的公共模块，文件消息与命令两处复用。
- 不新增依赖、不新增配置项、不改变最终回复的内容与裁决规则。

**Non-Goals:**

- 不处理启动期冷唤醒（`init_db` / `rebuild_index` 在事件循环启动前执行，上线通知迟到问题另议）。
- 不做跨消息的并发唤醒去重（single-flight）：冷盘瞬间多条消息各发一条提示的概率极低。
- 不将预热与下载 URL 解析的 HTTP 请求并发执行（热盘串行成本亚毫秒级）。
- 不改变 shutdown drain 语义；不清理 `.activity` 文件。

## Decisions

### 决策 1：单函数模块，探针与回调均注入

新增 `app/services/disk_warmup.py`，只暴露一个协程（概念形态，非最终签名约束）：

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

`os.path.exists(output_dir)` 走路径解析，挂载根目录 dentry 长期留在内核与 SMB/NFS 客户端缓存中，冷盘时可能直接缓存命中返回成功，磁盘并未被唤醒——30 秒后真正下载落盘时依旧卡死，预热形同虚设。写入 `.activity` 产生到达 NAS 服务端的 CREATE/写请求，`flush()` 后再 `os.fsync()` 将"磁盘就绪"确定地关在探针内。探针函数可放在 `file_storage.py`（已承担 output 目录落盘职责）或下载器中，由装配处绑定为 `probe` 传入；`.activity` 每次覆写为当前时间戳，单文件、无清理逻辑。

### 决策 4：接线点与"每条消息最多一次"

| 处理动作 | 接线位置 | 提示回调 |
|---|---|---|
| 单条 picture/video/file | `MediaFileHandler.handle` 提取出 `download_code` 之后、调用 `_process_one_image` 之前 | `pipeline.async_reply_text(WAKING_STORAGE_TEXT, message)` |
| richText 图片 | `_handle_rich_text` 过滤出非空 `picture_segments` 之后、逐张循环之前（整条消息一次） | 同上 |
| 重建索引命令 | `main.py` 的 `rebuild_index` 闭包内、`async_rebuild_index()` 之前 | 同上 |

在提取 `download_code` / 过滤图片段之后调用，保证缺失下载码、无图片段等"不碰盘"分支不产生 `.activity` 写入；text/audio 经处理器职责判断天然不进入接线点。探针在唤醒后盘即处于热态（NAS 休眠超时以分钟计，单条消息处理期间不会再次休眠），因此只需包住"第一次触碰"，无需包裹下载、落盘、SQLite 的完整序列。

### 决策 5：CommandAction 扩展 pipeline 参数

当前 `CommandAction = Callable[[ChatbotMessage, dict], Awaitable[str]]`，命令回调没有发送中间态消息的能力。扩展为三参 `(message, raw_data, pipeline)`，`CommandHandler` 调用处分发的是自身 `handle` 已收到的 pipeline 对象，改动面仅类型别名、调用点与 `main.py` 中一个闭包。回调的最终返回文本仍按 `PRIMARY` 意图走既有裁决，唤醒提示是该意图之外的独立消息（见决策 6）。

### 决策 6：中间态提示作为意图模型的唯一受控例外

现行规范要求"处理器 SHALL NOT 自行发送回复"。唤醒提示无法建模为 `ReplyIntent`：它是处理中途发出的进度消息，与最终回复必须同时存在而非竞争层级。因此在 `message-pipeline` 规范中为中间态进度提示开一个受控例外：可经 pipeline 直发、不参与裁决、不抑制最终回复、措辞固化，当前唯一用途为存储唤醒。实现上复用现成的 `pipeline.async_reply_text`，不为进度回调引入新的分发机制。

## Risks / Trade-offs

- **每条文件消息多一次 fsync**：热盘下为亚毫秒级，且仅发生在本来就要写盘的消息上，可接受。
- **并发消息重复提示**：冷盘瞬间到达 N 条消息会产生 N 条唤醒提示。已按 Non-Goals 接受；未来如有投诉再引入 single-flight（共享一个探针 future + 仅首个调用方挂回调），模块形态不需要推翻。
- **shutdown 期间探针线程不可取消**：与现有 SQLite `to_thread` 调用语义一致，由 `drain_active_tasks` 的 10 秒上限兜底；极端情况下探针随进程退出终止，`.activity` 为覆写文件无一致性问题。
- **NAS 语义差异**：fsync 对不同网络文件系统的刷盘语义有差异，但 CREATE+写+fsync 已足以触发服务端磁盘唤醒，不依赖特定 NAS 的缓存一致性保证。
