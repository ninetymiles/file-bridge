## MODIFIED Requirements

### Requirement: 信号拦截与优雅停机
系统 SHALL 拦截并统一处理操作系统的中断信号（`SIGINT`）与终止信号（`SIGTERM`），执行受控的停机流程并正常退出。停机序列 SHALL 通过取消 SDK 运行任务并关闭 websocket 终止长连接，对运行任务的等待 SHALL 是有界的（不超过 1 秒）。系统 SHALL NOT 依赖 SDK 的停止标志接口：当前锁定的 dingtalk-stream 0.24.3 不提供 `stop()` 方法与 `_stop_event`。有界等待结束后进程退出，从根本上阻止 SDK 在捕获 `CancelledError` 后的重连尝试。

#### Scenario: 收到终端中断信号 SIGINT
- **WHEN** 用户在控制台触发 `Ctrl-C` 产生 `SIGINT`
- **THEN** 系统记录停机日志，取消 SDK 运行任务，关闭底层网络连接，有界等待不超过 1 秒，且不抛出未捕获异常堆栈，以状态码 0 退出

#### Scenario: 收到容器停止信号 SIGTERM
- **WHEN** 容器管理系统（如 `docker stop`）向主进程发送 `SIGTERM`
- **THEN** 系统执行与 SIGINT 相同的取消与断开连接流程，并在有界等待后以状态码 0 正常退出

#### Scenario: 优雅停机期间的二次中断强退
- **WHEN** 优雅停机流程已启动（首次 `SIGINT`/`SIGTERM` 已处理）后用户再次触发 `Ctrl-C`
- **THEN** 系统 SHALL 立即抛出 `KeyboardInterrupt` 或以非零状态码退出，不再继续执行未完成的清理步骤，确保用户始终可强制终止进程

#### Scenario: 停机序列避免 SDK 自动重连
- **WHEN** 优雅停机开始且 SDK 运行任务被取消、websocket 连接被关闭
- **THEN** 即使 SDK 将 `CancelledError` 视为网络异常并在固定睡眠后尝试重连，系统 SHALL NOT 等待该重连循环，而是在不超过 1 秒的有界等待后结束进程，使重连不实际发生

### Requirement: BotService 异步生命周期协议
系统 SHALL 通过 `BotService` 类对外暴露稳定的异步生命周期协议，提供 `async start()` 与 `async stop()` 两个公开方法，封装 SDK 客户端、消息管线与生命周期通知器的初始化与清理。该协议 SHALL NOT 引入 ASGI / Uvicorn / FastAPI 依赖，调用方可为 CLI 脚本或未来 ASGI lifespan 钩子。

#### Scenario: 启动 BotService
- **WHEN** 调用方调用 `await BotService.start()`
- **THEN** 系统构造 `DingTalkStreamClient`、`Pipeline` 与 `LifecycleNotifier`，启动 SDK 后台协程任务，发送 online 通知（阻塞等待合理），bot 进入 running 状态

#### Scenario: 停止 BotService
- **WHEN** 调用方调用 `await BotService.stop()`
- **THEN** 系统执行修订后的 shutdown 序列（cancel runner task → fire-and-forget offline notify → close websocket → 有界等待不超过 1 秒），bot 进入 stopped 状态

#### Scenario: 启停协议幂等性
- **WHEN** 调用方对已 running 的 BotService 再次调用 `start()`，或对已 stopped 的 BotService 再次调用 `stop()`
- **THEN** 系统 SHALL 直接返回，不重复初始化或清理，不抛异常

#### Scenario: CLI 脚本作为调用方
- **WHEN** 通过 `python -m app.main` 启动
- **THEN** 系统 SHALL 通过同步入口 `run_forever()`（或 `run()` 工厂函数）以 `asyncio.run` 调用 `BotService.start_and_wait()`，注册 `SIGINT`/`SIGTERM` 信号回调触发 `stop()`
