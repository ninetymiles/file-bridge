## Why

停机时在途消息任务的处置目前是空白的：`BotService.stop()` 只取消 SDK 的 `start()` 循环任务，每条消息对应的处理任务由 SDK `asyncio.create_task` 派生且无引用追踪，最终被 `asyncio.run()` 收尾隐式摧毁——落在哪个 await 点全凭运气：`.tmp` 残留、文件落盘但元数据缺失、记录落库但无回复等撕裂状态都可能发生。需要为停机定义确定性的在途任务收尾语义：停止接收新任务、按任务所处阶段分类处置（未开始/下载中 → 中断；已下载完成 → 等待落库完成后退出）、全部收尾后再关闭 websocket 退出。

## What Changes

- `PipelineHandler` 增加在途任务追踪与停机门控：
  - `process()` 入口以 `asyncio.current_task()` 注册在途任务、`finally` 注销；入口检查 drain 标志，停机门关闭后新消息直接 ack-OK 秒退（不处理、不回复，SDK 照常发 ack 故钉钉不重投）。
  - 新增 `begin_drain()`（关门）与 `drain_active_tasks(timeout)`（分类处置 + 有界等待）。
  - 新增 `mark_download_done()`：任务在 `download_file_stream` 返回后同步标记"已过下载点"。
- `MediaFileHandler` 增加阶段检查点：
  - 下载开始前查 drain 标志：已关门则静默放弃（不下载、不落库、不回复）。
  - 下载中的任务被 drain 取消时，在 `except CancelledError` 中向来源回复"任务已取消/中断"后重新抛出；`.tmp` 临时文件由下载器清理。
  - **已过下载点的任务不设任何取消检查**：文件保存、元数据落库、成功回复必然完整执行。
- `FileDownloader.download_file_stream` 的清理分支 `except Exception` → `except BaseException`：使被取消任务的 `.tmp` 残留也被清理（`CancelledError` 不属于 `Exception`）。
- `BotService` 构造参数增加 `pipeline`，`stop()` 序列在取消 runner 任务**之前**插入 drain 阶段：关门 → 分类处置在途任务（有界等待 10 秒）→ 取消 runner 任务关闭 websocket → 离线通知 → 退出。websocket 是最后一个被关闭的资源。
- drain 等待上限 10 秒为进程内常量，不引入新配置项。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无——本变更为 `lifecycle-management` 新增一个独立需求"在途消息任务的优雅收尾"，不修改既有需求块，避免与在途变更 fix-filename-and-shutdown 对"信号拦截与优雅停机"的 delta 冲突）

### Added Requirements（归属于既有 capability `lifecycle-management`）

- 新增需求"在途消息任务的优雅收尾"（delta 见 `specs/lifecycle-management/spec.md`），覆盖：停机期间新消息不再处理、未开始下载的任务静默放弃、下载中的任务被中断并回复取消、已下载完成的任务必须完成落库与成功回复、有界等待兜底。

## Impact

- **代码**：
  - `lib/handlers.py`：`PipelineHandler` 增加追踪/门控/drain 方法（约 40 行）；`MediaFileHandler.handle` 增加检查点与取消回复分支（约 10 行）。
  - `lib/file_downloader.py`：1 处 except 子句放宽。
  - `lib/runner.py`：`BotService.__init__` 增加 `pipeline` 参数；`stop()` 头部插入两步（关门 + drain）；docstring 同步。
  - `app/main.py`：`create_pipeline` 与 `BotService(...)` 调用传参（1 行）。
- **实施顺序依赖**：须在 `fix-filename-and-shutdown` 归档后实施——该变更先重写 `stop()`（删除 `client.stop()` 死代码、等待 5s→1s），本变更在其产物之上插入 drain 阶段；两者的 `stop()` 改动分两次小步提交。
- **行为变化**：
  - 停机时在途文件任务不再被隐式摧毁：下载中的被打断且发件人收到"任务已中断"回复；已下载完成的保证落盘落库并回复成功。
  - 停机耗时上界从"立即"变为"最长约 10 秒 + 1 秒"（有在途任务时）；空闲时 drain 瞬时完成，停机耗时不变。
  - drain 期间新到达的消息只被 ack 不被处理（发件人无回复）。
- **已知边界**（详见 design）：`asyncio.to_thread` 中的 sqlite/HTTP 操作无法被精确打断，drain 超时后被放弃的任务其线程侧事务仍会跑完直至进程退出；单用户场景概率极低，sqlite journal 保证库文件不损坏。
- **依赖**：无新增第三方依赖。
