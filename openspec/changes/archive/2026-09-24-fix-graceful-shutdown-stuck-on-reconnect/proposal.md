## Why

当前 `BotRunner` 的优雅停机序列未调用 `dingtalk_stream.DingTalkStreamClient.stop()`，导致 SDK 内部的 reconnect 循环（`while not self._stop_event.is_set()`）在收到 `SIGINT` 后仍会继续执行：SDK 把被关闭的 websocket 当成网络异常，触发自动重连开新连接，新连接又被 runner 关闭，进入死循环；同时 `_is_shutting_down` 短路了后续所有 `Ctrl-C`，用户无法强退。设计文档原本要求"主动断开底层连接"，实现与设计存在偏差。

## What Changes

### Phase 1: 紧急修 bug（shutdown 序列与二次强退）
- shutdown 序列第一步改为 `await self.client.stop()`，让 SDK 内部的 `_stop_event` 被显式 set，使 reconnect 循环正常退出，避免被 SDK 当作网络异常触发重连
- 调整 shutdown 顺序：先停止 SDK（`client.stop()` + `runner_task.cancel()`），再发送 offline 通知，避免 SDK 在通知发送窗口（最长 5 秒）内继续重连
- offline 通知改为 fire-and-forget 模式（`asyncio.create_task`），避免通知网络异常阻塞停机
- `_is_shutting_down` 增加二次强退支持：首次 SIGINT 触发优雅停机，第二次 SIGINT 直接 `raise KeyboardInterrupt` 退出，确保用户始终有 escape hatch
- `request_stop()` 调用 `client.stop()` 时使用 fire-and-forget 方式触发，不阻塞信号处理路径

### Phase 2: BotService 解耦（不引入 ASGI 运行时）
- 将 `BotRunner` 重构为 `BotService`，对外暴露稳定的异步协议：`async start()` / `async stop()`
- `start()` 负责构造 `Pipeline`、`LifecycleNotifier`、`DingTalkStreamClient`，启动 SDK 后台 task，发送 online 通知
- `stop()` 复用 Phase 1 修订后的 shutdown 序列（client.stop → cancel → fire-and-forget offline notify → close ws）
- 保留同步入口 `start_forever()`（或新建 `run()` 工厂函数）以兼容现有 CLI 启动方式
- 不引入 Uvicorn、FastAPI 或 ASGI 依赖，本变更不规定调用方

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `lifecycle-management`: 修订"信号拦截与优雅停机"需求，要求 shutdown 序列先调用 SDK 的 `stop()` 再关闭 websocket 与 task；新增"二次中断强退"场景；新增"BotService 异步生命周期协议"需求（start/stop 接口契约）

## Impact

- **代码**：`lib/runner.py`（shutdown 序列、信号处理、二次强退逻辑、BotService 重构），`lib/lifecycle_notifier.py`（offline 通知 fire-and-forget 模式），`app/main.py`（适配 BotService 同步入口）
- **APIs**：BotService 对外提供 `async start()` / `async stop()` 协议，供未来 ASGI lifespan 钩子消费
- **依赖**：不修改第三方 SDK 源码，依赖 SDK 现有的 `stop()` 方法；不引入 Uvicorn / FastAPI / ASGI 依赖
- **后续变更**：`integrate-fastapi-framework` 将消费 BotService API，在 FastAPI lifespan 钩子里调用 `bot.start()` / `bot.stop()`
- **测试**：需补充 runner shutdown 序列与 BotService 接口契约的单元测试覆盖新行为
