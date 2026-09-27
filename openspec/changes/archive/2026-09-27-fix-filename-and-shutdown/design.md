## Context

两处存量缺陷（详见 proposal.md — Why）。对 `lib/runner.py` 完成全文复读后，须修正探索阶段的一个判断：`self._stop_event`（runner.py:63）是 **BotService 自身持有的** `asyncio.Event`，用于 `start_and_wait()` 的阻塞等待（runner.py:150），由 `request_stop()` 的 runner.py:180-181 设置——该段是活代码，保留。真正的死代码仅两处：

1. `stop()` 步骤 1（runner.py:106-112）：`await asyncio.wait_for(self.client.stop(), timeout=5.0)`，SDK 0.24.3 无 `stop()`，必抛 AttributeError 被 WARNING 吞掉。
2. `request_stop()` 内 runner.py:173-179：`getattr(self.client, "_stop_event", None)` 段，SDK 无该私有属性，getattr 恒为 None 后整段空转。

## Goals / Non-Goals

**Goals:**

- 文件名时间戳按 85e96bc 意图定型：`YYYYMMDD_HHMMSS_fff`（3 位毫秒）。
- 删除上述两段死代码，停机日志不再出现 AttributeError 警告。
- 停机耗时从约 5.1 秒降至约 0.1~1.1 秒；退出码与通知时序不变。
- 保持 BotService 自身 `_stop_event` 的唤醒机制、二次中断强退、幂等性不变。

**Non-Goals:**

- 不修改 dingtalk-stream SDK（不消除 SDK 自身的 `[start] network exception` 日志、不改其重连实现）。
- 不重构 runner.py 结构、不合并 `start_and_wait`、不动信号注册的 Windows fallback。
- 不改 file-storage 规范（`[发送者]_时间戳.原扩展名` 对新格式仍成立）。
- 不引入 asyncio task group 或新的停机抽象。

## Decisions

1. **文件名截断 `[:18]` → `[:19]`，不回滚 85e96bc。**
   - commit 明确有改格式意图（标题 "Update stored file name"），回滚会丢弃该意图；`[:19]` 恰好取到 `%f`（6 位微秒）的前 3 位，即毫秒。
   - 字符账：`%Y%m%d_%H%M%S_%f` → 22 字符，前 19 字符 = 日期 8 + `_` + 时间 6 + `_` + 毫秒 3。
   - 备选回滚 `%Y%m%d%H%M%S_%f[:18]` 被否（前述理由）。
2. **删除 `stop()` 步骤 1 整段（含 try/except 与 TimeoutError 分支），不保留任何 `hasattr` 防御。**
   - 备选 `hasattr(self.client, "stop")` 守卫：拒绝死代码的兼容包装；锁定版本 0.24.3 已确认无此方法，若未来 SDK 提供再按新能力设计。
3. **删除 `request_stop()` 中对 SDK 的 getattr 段（runner.py:173-179），保留紧随其后对自身 `self._stop_event` 的设置（180-181）。**
   - 两个 `_stop_event` 同名但归属不同，这是探索期差点误删的点；实施时以行段而非标识符为删除单位。
4. **runner task 等待 `timeout=5.0` → `1.0`。**
   - cancel 瞬间 `CancelledError` 已传入 SDK 的 `async for`，`async with websockets.connect` 立即退场并发送 CLOSE 1000——网络层在毫秒级完成关闭。
   - SDK 在 except 分支固定 `await asyncio.sleep(10)` 后 continue，等待其任务结束必然超时；5 秒与 1 秒结果相同（都超时），1 秒只作为网络关闭的兜底宽限。
5. **超时日志 WARNING → INFO，文案改为陈述设计行为而非故障。**
   - 新文案要点：runner task 未在 1 秒内结束（SDK 捕获取消后进入固定睡眠），任务将随进程退出被抛弃。每次停机必现的事件不应以 WARNING 制造"出错了"的假象，符合"诚实日志"。
6. **同步更新 `stop()` docstring**：删除"步骤 1 client.stop()"的描述与对旧变更路径的引用，步骤重编号为 4 步（cancel → notify → close ws → sleep(0.1)）；不改变实际执行顺序（删段后其余步骤原序上移）。

## Risks / Trade-offs

- [1 秒内未完成的在途消息处理协程被抛弃] → 消息处理协程由 SDK `create_task` 发起，停机边界本就不保证处理完在途消息；现状 5 秒等待同样只等 SDK 的 start() 任务、不等消息任务，行为无回退。
- [loop 关闭时 pending 的 SDK 任务产生 "Task was destroyed" 噪音] → 现有 5 秒路径下该任务同样 pending，验证时专门 grep 该日志；Python 3.14 对无异常的 pending 任务默认静默，如有噪音属于既有现象。
- [未来升级 SDK 获得 stop() 后代码未利用] → pyproject 锁定 `>=0.24.3`，升级时需重新评估；以 spec 新表述（取消 + 有界等待）为准入基线，新能力另行设计。
