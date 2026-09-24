## Context

`BotRunner`（`lib/runner.py`）当前在 `SIGINT`/`SIGTERM` 触发后执行 shutdown 序列：发 offline 通知 → `websocket.close()` → `runner_task.cancel()`。但序列中**从未调用 `dingtalk_stream.DingTalkStreamClient.stop()`**，导致 SDK 内部 `_stop_event` 未被设置，其 reconnect 循环 `while not self._stop_event.is_set()` 把 `websocket.close()` 当作网络异常继续重连，形成"close → 重连开新 ws → 又被关 → 再重连"死循环。

此外 `_is_shutting_down` 短路让首次 SIGINT 之后的所有 `Ctrl-C` 变成 no-op，用户无法强退，只能 kill 进程。

参见 proposal.md 的 Why 部分关于设计与实现偏差的描述。SDK `stop()` 实现见 `third-party/dingtalk-stream-sdk-python/dingtalk_stream/stream.py`。

## Goals / Non-Goals

**Goals:**
- 让 SDK 的 reconnect 循环在收到信号后能正常退出，不再开新连接
- 保持用户始终可通过二次 `Ctrl-C` 强退的能力
- offline 通知失败或超时不阻塞关键停机路径
- 对外暴露稳定的 `BotService` 异步生命周期协议（`async start()` / `async stop()`），便于后续 ASGI lifespan 钩子直接消费

**Non-Goals:**
- 不修改第三方 SDK 源码
- 不更改 online 通知的行为（启动时阻塞等待合理，无需 fire-and-forget）
- 不引入新的进程管理框架（supervisord、s6 等）
- 不引入 Uvicorn / FastAPI / ASGI 依赖，不规定调用方（CLI 脚本继续以 `asyncio.run` 作为入口；ASGI 集成留给 `integrate-fastapi-framework`）

## Decisions

### 1. shutdown 序列：先 `client.stop()`，再发通知
```text
+---------------------------------------------------------------+
|                 修订后的 shutdown 序列                          |
+---------------------------------------------------------------+
| 1. await self.client.stop()        # set SDK _stop_event      |
| 2. self._runner_task.cancel()      # 主动取消 SDK start task   |
| 3. await self._runner_task         # 等待 SDK 退出 (短超时)    |
| 4. fire-and-forget offline notify  # 不阻塞                    |
| 5. close websocket if still open                               |
| 6. exit 0                                                      |
+---------------------------------------------------------------+
```

**为何先 stop 再 cancel 再通知**：
- `client.stop()` 是协作式停止：set SDK 的 `_stop_event`，让 SDK 的 `while` 循环下一轮自然退出，避免被当作异常
- `runner_task.cancel()` 兜底处理 SDK 在阻塞调用中（如 `run_in_executor` 里的同步 HTTP）的情况
- offline 通知放在最后且 fire-and-forget，因为通知失败不能阻止停机

**替代方案考虑**：
- *先 cancel task 再 stop*：cancel 会让 SDK 抛 `CancelledError`，SDK 的 `finally` 块会尝试关 ws、清 connection_tasks（有 5 秒超时），可能比 stop 更慢
- *保留原顺序但加 `client.stop()`*：offline 通知最长 5 秒，期间 SDK 仍可能重连，治标不治本

### 2. `request_stop()` 里同步触发 `client.stop()`
信号回调里直接调用 `self.client.stop()` 的非异步版本（即只 set event，不做 await）：

```python
def request_stop(self, signame=None):
    if self._is_shutting_down:
        # Second signal: force exit
        raise KeyboardInterrupt
    self._is_shutting_down = True
    # Set SDK stop event immediately, non-blocking
    if self.client._stop_event is not None and not self.client._stop_event.is_set():
        self.client._stop_event.set()
    if self._stop_event and not self._stop_event.is_set():
        self._stop_event.set()
```

这样信号到达时 SDK 立刻知道要停，不等主循环 `await self._stop_event.wait()` 的 await 点才生效。

### 3. 二次 `Ctrl-C` 强退
`_is_shutting_down=True` 后再次进入 `request_stop()`，直接 `raise KeyboardInterrupt`，绕过 asyncio 事件循环的 await 阻塞，让 `asyncio.run()` 顶层捕获并退出。

**为何不用 `sys.exit(1)`**：`KeyboardInterrupt` 更符合 Unix 惯例，且 `start_forever()` 的 `try/except (KeyboardInterrupt, SystemExit)` 已能捕获。

### 4. offline 通知 fire-and-forget
```python
# Create task but don't await - failure must not block shutdown
asyncio.create_task(self.notifier.send_offline_notification())
```

通知任务自带 5 秒超时保护（见 `LifecycleNotifier.send_notification`），即使进程退出前任务没完成也不影响退出码。

## Risks / Trade-offs

- **[Risk] `client._stop_event` 在 SDK 升级后可能改名或语义变化**
  → **Mitigation**：优先调用 SDK 公开方法 `client.stop()`（async），仅在信号回调的同步路径里直接 set event；写注释说明这是对 SDK 内部状态的直接访问，升级需复核

- **[Risk] fire-and-forget 通知任务在进程退出前没机会执行**
  → **Mitigation**：在 `asyncio.run()` 退出前 await 一个极短 sleep（如 0.1s）给事件循环机会跑通知任务；或在 `start_forever()` 的 except 里给一点时间。考虑到通知本身是 best-effort，可接受丢失

- **[Risk] 二次 `Ctrl-C` 在 `asyncio.run()` 内可能仍被 swallow**
  → **Mitigation**：`start_forever()` 已有 `except (KeyboardInterrupt, SystemExit)`，二次信号抛出后会冒到顶层；测试覆盖此路径

- **[Trade-off] 离线通知可靠性下降**
  → fire-and-forget 意味着通知可能丢，但比起阻塞停机导致用户狂按 Ctrl-C 才能退，这个 trade-off 是值得的。如需可靠通知，可后续改为在 SIGTERM 前通过 healthcheck 提前触发

### 5. Phase 2: BotService 异步生命周期协议

将 `BotRunner` 重构为 `BotService`，对外暴露协议式 API，不规定调用方：

```python
class BotService:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

# CLI 入口保留同步封装
def run_forever() -> None:
    bot = BotService(...)
    try:
        asyncio.run(bot.start_and_wait())  # 内部 await stop_event
    except KeyboardInterrupt:
        ...
```

**为何做成 BotService**：
- 让 shutdown 序列（Phase 1 修订后的逻辑）成为可被外部任意调用方消费的协议，包括未来 ASGI lifespan 钩子
- `start()` / `stop()` 是 idempotent 协议接口，调用方可以选择何时启动与停止
- 避免调用方需要懂 SDK 内部的 `_stop_event`、`runner_task`、`websocket` 等私有状态

**为何不直接做 lifespan**：
- lifespan 是 ASGI 协议规范，需要 ASGI Server（Uvicorn）触发；在 `fix-graceful-shutdown` 里引入 Uvicorn 会让 bug 修复变更超载
- BotService 协议不规定调用方：CLI 脚本以 `asyncio.run` 调用，ASGI lifespan 以 `@asynccontextmanager` 调用，二者均可消费
- 让 `integrate-fastapi-framework` 的 lifespan 钩子直接 `await bot.stop()`，shutdown 序列逻辑已被本变更修对，避免再次写错顺序

**协议契约**：
- `start()` 完成后 bot 处于 running 状态；多次调用幂等（已 running 时直接返回）
- `stop()` 完成后 bot 进入 stopped 状态；多次调用幂等（已 stopped 时直接返回）
- `start()` 失败时 `stop()` 不应被调用（调用方负责）；`stop()` 内部对未初始化状态做防御性处理
