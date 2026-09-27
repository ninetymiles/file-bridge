## Context

现状（详见 proposal.md — Why）：每条消息由 SDK `asyncio.create_task(background_task(...))` 派生独立任务且无引用；`stop()` 只取消 runner 任务，在途消息任务被 `asyncio.run()` 收尾隐式摧毁。消息链路本身已是全协程（httpx 真异步流式下载、sqlite/HTTP 经 `asyncio.to_thread`），且下载先落 `.tmp`、完成后由 `save_file` 原子移交——"下载点"天然构成任务的可中断/不可中断分界。

前置依赖：须在 `fix-filename-and-shutdown` 归档后实施（该变更先完成 `stop()` 的死代码清理与 1 秒有界等待）。本变更不修改其 delta 涉及的既有需求块，只新增需求，避免两个变更对同一 MODIFIED 块的归档冲突。

## Goals / Non-Goals

**Goals:**

- 停机时在途任务按阶段分类收尾：未开始下载 → 静默放弃；下载中 → 取消 + 回复"已中断" + 清理 `.tmp`；已下载完成 → 完整执行保存/落库/成功回复。
- websocket 最后关闭；drain 有界（10 秒常量）。
- 空闲停机行为与现状一致（drain 瞬时完成）。

**Non-Goals:**

- 不改动 SDK 包、不 fork、不用 task factory 全局钩子。
- 不给 `CommandHandler`（重建索引等长任务）单独设检查点——它们与"已过下载点"任务同等对待：drain 窗口内自然跑完，超时放弃。
- 不新增配置项（10 秒上限为模块常量）。
- 不为 drain 期间被拒的新消息补发提示回复。

## Decisions

1. **任务追踪用 `asyncio.current_task()`，在 `process()` 入口注册、`finally` 注销。**
   - 备选：`loop.set_task_factory` 全局追踪——侵入面大且会裹挟 SDK 内部 keepalive 等任务；`current_task()` 精确圈定"正在处理消息"的任务集合。
2. **门控（gate）与分类处置共用一个 drain 标志；gate 命中的新消息不注册进追踪集合。**
   - 被 gate 拒绝的任务不做任何事，无需 drain 覆盖；注册发生在 gate 检查之后，快照集合即"真实在干活"的任务。
   - gate 期间 SDK 可能重连（`fix-filename-and-shutdown` 已确认 0.24.3 的 `start()` 捕获 CancelledError 后 `sleep(10)` 继续），但重连涌入的消息一律被 gate 拒绝——drain 收敛与重连与否无关，这是"ws 最后关"顺序成立的关键。
3. **阶段标记用同步赋值 `mark_download_done()`，紧贴 `download_file_stream` 返回之后、任何 await 之前。**
   - 事件循环内"标记"与"检查"之间无 await 即无交错：drain 的取消循环为纯同步代码（检查未标记 → 立即 `task.cancel()`），不存在"取消瞬间任务刚过下载点"的竞态。
   - 备选：在下载器内部埋标记——跨层传递状态，不如让 handler 层自持。
4. **下载中的任务由 drain 统一 `task.cancel()`，任务自身在 `except CancelledError` 中回复"已中断"后 `raise`。**
   - 取消打进 `aiter_bytes` 的 await 点，httpx 流被关闭；回复在取消送达后的同一个任务内执行（取消只投递一次，捕获后的 await 正常运行），消息上下文（sender/message）天然在手，无需编排器复制。
   - 备选：编排器代为回复——需在状态对象里复制 message 上下文，多一份状态无收益。
5. **已过下载点的任务零检查点：`save_file` → `async_insert_record` → 成功回复无条件完整执行。**
   - 这是用户语义的核心保证："已下载完成的，才等它落库以后回复任务成功自然退出"。drain 对这些任务只等待、不动手。
6. **`download_file_stream` 清理分支 `except Exception` → `except BaseException`。**
   - `CancelledError` 继承自 `BaseException`，现状清理分支不匹配导致取消后 `.tmp` 残留；放宽后中断下载的临时文件被清理，与 spec"清理已产生的临时文件"对应。
7. **drain 等待 `asyncio.wait(快照, timeout=10)`；超时后放弃剩余任务并记录 INFO 陈述性日志（非 WARNING）。**
   - 超时是兜底而非故障：剩余任务只可能是"已过下载点但落库/回复未完"或 to_thread 中未返回者；放弃等待后随进程退出，线程侧事务自然收尾。
8. **`BotService` 构造参数增加 `pipeline`，`stop()` 序列变为：关门 → drain(10s) → cancel runner(1s，沿用前置变更产物) → 离线通知 → sleep(0.1)。**
   - 离线通知保持在关 ws 之前（符合 lifecycle spec"断开长连接前"）；drain 期间离线通知未发，若 drain 耗时长，通知延迟数秒——可接受（fire-and-forget 本就不承诺即时）。

## Risks / Trade-offs

- [drain 最长增加约 10 秒停机耗时] → 仅在有在途任务时发生；空闲时 `asyncio.wait` 对空集合瞬时返回。
- [to_thread 中的操作不可精确打断] → drain 超时后放弃等待，线程侧 sqlite 事务跑完（journal 保证不损坏），task 侧不再等待不回复；单用户机器人概率极低，接受。
- [取消送达后任务内回复依赖"取消只投递一次"的 asyncio 行为] → drain 编排器对每个任务只 cancel 一次；二次 Ctrl-C 走既有强退路径（KeyboardInterrupt），不会对同一任务二次 cancel。
- [gate 拒绝的消息发件人无任何反馈] → 停机窗口秒级，且补发"维护中"回复属于新增交互，超出本变更范围。
- [与本变更及前置变更共同改动 `stop()`] → 分两次实施归档，各自独立验证；本变更任务清单假定前置变更产物已合入。
