## ADDED Requirements

### Requirement: FastAPI Lifespan 钩子消费 BotService
系统 SHALL 在 FastAPI 应用实例上注册 lifespan 上下文管理器，在 startup 阶段调用 `await BotService.start()`，在 shutdown 阶段调用 `await BotService.stop()`。lifespan 钩子 SHALL 作为 BotService 协议的调用方，不直接实现 SDK 客户端、Pipeline 与 LifecycleNotifier 的初始化与 shutdown 序列（由 `fix-graceful-shutdown-stuck-on-reconnect` 变更负责）。

#### Scenario: Lifespan 驱动启动
- **WHEN** Uvicorn 收到启动信号并触发 FastAPI lifespan startup 阶段
- **THEN** 系统 SHALL 在 lifespan 钩子内调用 `await BotService.start()`，启动 SDK 后台协程任务并发送 online 通知，bot 进入 running 状态

#### Scenario: Lifespan 驱动停机
- **WHEN** Uvicorn 收到 `SIGINT`/`SIGTERM` 并触发 FastAPI lifespan shutdown 阶段
- **THEN** 系统 SHALL 在 lifespan 钩子的 `finally` 块中调用 `await BotService.stop()`，由 BotService 内部执行修订后的 shutdown 序列（client.stop → cancel → fire-and-forget offline notify → close ws），bot 进入 stopped 状态

#### Scenario: Lifespan 钩子启动失败
- **WHEN** `BotService.start()` 在 lifespan startup 阶段抛出异常
- **THEN** 系统 SHALL 让 lifespan 进入 failed startup，Uvicorn 不会触发 shutdown 阶段；如 `BotService` 已部分初始化，由 BotService 内部做防御性回滚，lifespan 钩子无需自行清理
