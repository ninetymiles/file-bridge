## MODIFIED Requirements

### Requirement: 信号拦截与优雅停机
系统 SHALL 拦截并统一处理操作系统的中断信号（`SIGINT`）与终止信号（`SIGTERM`），执行受控的停机流程并正常退出。停机序列 SHALL 优先调用底层 Stream 客户端的 `stop()` 以显式设置 SDK 内部停止标志，再关闭 websocket 与取消运行任务，避免被 SDK 视为网络异常而触发自动重连。

#### Scenario: 收到终端中断信号 SIGINT
- **WHEN** 用户在控制台触发 `Ctrl-C` 产生 `SIGINT`
- **THEN** 系统记录停机日志，调用 Stream 客户端 `stop()` 设置 SDK 停止标志，取消运行任务，关闭底层网络连接，且不抛出未捕获异常堆栈，以状态码 0 退出

#### Scenario: 收到容器停止信号 SIGTERM
- **WHEN** 容器管理系统（如 `docker stop`）向主进程发送 `SIGTERM`
- **THEN** 系统执行完整的清理与断开连接流程，并在宽限期内以状态码 0 正常退出

#### Scenario: 优雅停机期间的二次中断强退
- **WHEN** 优雅停机流程已启动（首次 `SIGINT`/`SIGTERM` 已处理）后用户再次触发 `Ctrl-C`
- **THEN** 系统 SHALL 立即抛出 `KeyboardInterrupt` 或以非零状态码退出，不再继续执行未完成的清理步骤，确保用户始终可强制终止进程

#### Scenario: 停机序列避免 SDK 自动重连
- **WHEN** 优雅停机开始且 SDK 内部的 websocket 连接被关闭
- **THEN** 系统 SHALL 已先行调用 `client.stop()` 设置 SDK 的 `_stop_event`，使 SDK 的 reconnect 循环（`while not self._stop_event.is_set()`）正常退出，不被视为网络异常触发重连

## ADDED Requirements

### Requirement: 离线通知的非阻塞性
系统在优雅停机序列中发送离线通知 SHALL 采用 fire-and-forget 模式，通知发送的成败或超时 SHALL NOT 阻塞或延缓 SDK 停止与 websocket 关闭的关键路径。

#### Scenario: 离线通知发送失败不阻塞停机
- **WHEN** 优雅停机序列开始执行且离线通知因网络异常发送失败或超时
- **THEN** 系统记录 WARNING 日志但不等待通知任务完成，继续完成 SDK 停止与连接关闭流程

### Requirement: BotService 异步生命周期协议
系统 SHALL 通过 `BotService` 类对外暴露稳定的异步生命周期协议，提供 `async start()` 与 `async stop()` 两个公开方法，封装 SDK 客户端、消息管线与生命周期通知器的初始化与清理。该协议 SHALL NOT 引入 ASGI / Uvicorn / FastAPI 依赖，调用方可为 CLI 脚本或未来 ASGI lifespan 钩子。

#### Scenario: 启动 BotService
- **WHEN** 调用方调用 `await BotService.start()`
- **THEN** 系统构造 `DingTalkStreamClient`、`Pipeline` 与 `LifecycleNotifier`，启动 SDK 后台协程任务，发送 online 通知（阻塞等待合理），bot 进入 running 状态

#### Scenario: 停止 BotService
- **WHEN** 调用方调用 `await BotService.stop()`
- **THEN** 系统执行修订后的 shutdown 序列（`client.stop()` → cancel runner task → fire-and-forget offline notify → close ws），bot 进入 stopped 状态

#### Scenario: 启停协议幂等性
- **WHEN** 调用方对已 running 的 BotService 再次调用 `start()`，或对已 stopped 的 BotService 再次调用 `stop()`
- **THEN** 系统 SHALL 直接返回，不重复初始化或清理，不抛异常

#### Scenario: CLI 脚本作为调用方
- **WHEN** 通过 `python -m app.main` 启动
- **THEN** 系统 SHALL 通过同步入口 `run_forever()`（或 `run()` 工厂函数）以 `asyncio.run` 调用 `BotService.start_and_wait()`，注册 `SIGINT`/`SIGTERM` 信号回调触发 `stop()`
