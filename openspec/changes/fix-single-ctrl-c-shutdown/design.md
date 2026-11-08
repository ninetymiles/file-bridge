# Design

## Context

见 proposal.md - Why。当前实现的关键约束：

- `BotService.stop()` 用 `asyncio.wait_for(self._runner_task, timeout=1.0)` 等待被取消的 SDK 运行任务（`app/core/runner.py`）。
- SDK 0.24.3 的 `DingTalkStreamClient.start()` 把 `CancelledError` 与 `ConnectionClosedError` 一起当作网络异常：记录日志后 `await asyncio.sleep(10)` 并 `continue` 重连。该 `except` 块本身不被同一层 `try` 保护，因此只有在 `sleep(10)` 期间收到的取消才会真正结束任务。
- Python 3.11+ 的 `wait_for` 由 `asyncio.timeout` 实现：超时取消的是“正在 await 的调用方任务”，其 `CancelledError` 只有在被等待的任务真正结束时才投递。被等待任务吞掉取消并继续重连时，调用方永远不恢复。

实测日志时序印证：首次取消落在 `async for` → SDK 捕获并完成 ws close 握手（约 1 秒）→ 该 1 秒内 `wait_for` 超时发出的第二次取消又落在 try 体内 → 再次被吞 → SDK 睡 10 秒后重连；`stop()` 从此挂起，`asyncio.run` 的 teardown 也等待该任务，用户只能再按 2 次 `Ctrl-C`，容器则只能等 Docker 在 10 秒宽限期后 `SIGKILL`。

容器侧约束：`docker-compose.yml` 未设置 `stop_grace_period`，使用 Docker 默认 10 秒；而 `drain_active_tasks(timeout=10.0)` 单独就可能用满该预算。

## Goals / Non-Goals

**Goals:**

- 空闲状态下，单次 `Ctrl-C` / 单个 `SIGTERM` 在取消预算（≤1 秒）内完成停机并以 0 退出。
- 取消等待不阻塞调用方任务：预算到期即继续后续步骤。
- SDK 运行任务在首次取消被吞掉后，仍能在预算内被终止。
- 容器部署的停止宽限期大于停机序列上界，避免优雅停机被 `SIGKILL` 截断。
- 二次信号成为真正的强退，不依赖 `asyncio.run` teardown。

**Non-Goals:**

- 不修改第三方 SDK 源码，不消除 SDK 自身的 `[start] network exception` 日志。
- 不消除 SDK `open_connection()` 同步 `requests.post` 无超时导致的阻塞风险（见 Risks）。
- 不调整 drain 的 10 秒上限，也不改变在途消息的分类收尾语义。
- 不重构 `BotService` 的启停协议、信号注册或通知时序。

## Decisions

### 1. 用“有界反复取消”替代 `wait_for` 单次等待

```text
deadline = now + 1.0
while not task.done() and now < deadline:
    task.cancel()                          # 每轮补发，总有一发落在 SDK 的 sleep(10) 上
    await asyncio.wait({task}, timeout=0.1) # 到期即返回，不取消调用方
```

- `asyncio.wait` 在超时后直接返回，不等待被等待任务完成，也不取消调用方任务，因此 `stop()` 的 1 秒预算是真实可兑现的。
- 每 0.1 秒补发一次取消：落在 `async for` 或 ws close 握手时会被 SDK 吞掉，但下一次会落在 `sleep(10)` 上并逃出 `start()`。已用 SDK 同构协程（含抗取消的 close 握手）验证，约 0.3~0.4 秒内任务进入 `cancelled()`，`asyncio.run` 无 pending 任务噪音退出。

**替代方案：**

| 方案 | 拒绝理由 |
| --- | --- |
| 保留 `wait_for`、调大 timeout | 超时语义问题不随 timeout 改变，只是拉长卡住时间 |
| `cancel()` + `await task` | 同上，被吞掉后永不返回 |
| 自己管理 loop、跳过 `_cancel_all_tasks` | 改动面大，会产生 `Task was destroyed` 噪音，且需重写 `run_forever` |
| SDK 循环放独立 daemon 线程 | 跨事件循环的 drain/通知复杂化，超出本次修复范围 |

### 2. 二次信号直接终止进程

`request_stop()` 的“已在停机中”分支改为先记录 WARNING 并 flush 日志处理器，再 `os._exit(130)`。

- `raise KeyboardInterrupt` / `SystemExit` 都会穿过 `asyncio.run` 的 `Runner.close()` → `_cancel_all_tasks`，若运行任务仍在重连，强退仍会被阻塞（实测需要第三次 `Ctrl-C`）。
- `os._exit` 绕过所有清理，是唯一可靠的强退语义；仅由人工二次信号触发，不影响容器（Docker 只发送一次 `SIGTERM`）。

**替代方案**：`signal.raise_signal(SIGKILL)` 不可移植到非 POSIX，且语义更隐晦。

### 3. 容器停止宽限期

`docker-compose.yml` 的 `bridge` 服务增加 `stop_grace_period: 20s`，覆盖 `drain 10 秒 + 取消预算 1 秒 + 关连接与通知` 的上界。不改 drain 上限，避免改变既有在途任务收尾语义。

**替代方案**：把 drain 从 10 秒降到 6 秒。会直接缩短在途落库的允许时间，影响数据完整性，故不采用。

### 4. 规范修正

`lifecycle-management` 中的“有界等待结束后进程退出，从根本上阻止重连”改写为“等待有界且不阻塞调用方，持续补发取消直至任务结束或预算耗尽”，并明确二次信号为立即终止进程。原表述与 `asyncio.run` 的 teardown 行为矛盾，是本次缺陷的规范根源。

### 5. 测试策略

测试必须模拟“吞掉一次取消”的 runner task，而不是配合型的 mock：

```python
async def stubborn_start():
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await asyncio.sleep(10)   # 首次取消被吞，进入重连前睡眠
```

断言：`request_stop()` 后 `start_and_wait()` 在 2 秒内返回、`_runner_task.cancelled()` 为真、调用方未收到超时异常。另需覆盖二次信号的进程终止路径（用 patch 替换 `os._exit` 验证被调用及退出码 130）。

## Risks / Trade-offs

- [SDK `open_connection()` 的同步 `requests.post` 无超时会阻塞事件循环] → 此时任何取消与预算计时都无法投递，进程只能被外部 `SIGKILL`。属于 SDK 既有缺陷，本次不处理；如需处理应单独提案（如外层加进程级看门狗）。
- [每 0.1 秒补发取消会累积 `cancelling` 计数] → 任务最终以 `CancelledError` 结束，属预期；测试断言 `task.cancelled()`。
- [`os._exit(130)` 跳过离线通知与 ws 关闭] → 仅在人工二次信号时触发，语义就是“立即放弃清理”；日志先 flush，容器内 `PYTHONUNBUFFERED=1` 不受影响。
- [SDK 升级后取消语义变化] → 取消策略不依赖 SDK 私有字段，仅依赖“任务必须结束”这一公开行为；升级时补充冒烟验证。
- [`stop_grace_period` 与 drain 上限耦合] → 若未来调整 drain 上限，需同步复核该配置；在 design 中记录该约束。
