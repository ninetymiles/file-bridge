# lifecycle-management Specification

## Purpose

规范机器人运行时的生命周期管理，提供进程信号拦截与优雅停机支持，并在服务启动上线与停机离线时执行受控的状态通知。

## Requirements

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

### Requirement: 上线与离线主动通知
系统 SHALL 支持在服务启动就绪后及停机清理前向预设的钉钉会话发送状态通知，且在未配置目标时保持静默。

#### Scenario: 配置了通知目标时的上线通知
- **WHEN** 配置了有效的群聊 ID 或单聊用户 ID 且服务初始化就绪
- **THEN** 系统向指定会话发送“服务已上线”的主动通知消息

#### Scenario: 配置了通知目标时的离线通知
- **WHEN** 配置了有效的群聊 ID 或单聊用户 ID 且接收到停机信号
- **THEN** 系统在断开长连接前向指定会话发送“服务正在离线”的主动通知消息

#### Scenario: 未配置通知目标时的静默处理
- **WHEN** 未配置任何通知目标（既无群聊 ID 亦无单聊用户 ID）
- **THEN** 系统跳过上下线通知发送流程，不记录错误且不阻断应用的正常启动和停机

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
- **THEN** 系统执行修订后的 shutdown 序列（cancel runner task → fire-and-forget offline notify → close websocket → 有界等待不超过 1 秒），bot 进入 stopped 状态

#### Scenario: 启停协议幂等性
- **WHEN** 调用方对已 running 的 BotService 再次调用 `start()`，或对已 stopped 的 BotService 再次调用 `stop()`
- **THEN** 系统 SHALL 直接返回，不重复初始化或清理，不抛异常

#### Scenario: CLI 脚本作为调用方
- **WHEN** 通过 `python -m app.main` 启动
- **THEN** 系统 SHALL 通过同步入口 `run_forever()`（或 `run()` 工厂函数）以 `asyncio.run` 调用 `BotService.start_and_wait()`，注册 `SIGINT`/`SIGTERM` 信号回调触发 `stop()`

### Requirement: 在途消息任务的优雅收尾
系统在停机流程中 SHALL 对在途消息处理任务执行分类收尾：先关闭任务准入（此后到达的新消息仅确认不处理），再按任务所处阶段处置——未开始下载的任务 SHALL 直接放弃；下载中的任务 SHALL 被取消中断并向消息来源回复任务已取消或中断；已下载完成的任务 SHALL NOT 被中断，系统 SHALL 等待其完成文件保存、元数据落库与成功回复后自然退出。整个收尾等待 SHALL 是有界的（不超过 10 秒），超时后系统 SHALL 放弃剩余任务并继续停机流程。websocket 连接 SHALL 在所有在途任务收尾结束后才被关闭。

#### Scenario: 停机期间新消息不再处理
- **WHEN** 停机流程已开始（任务准入已关闭）且 websocket 仍有新消息到达
- **THEN** 系统正常返回确认（SDK 照常发送 ack，平台不重投），但不执行任何处理逻辑，不产生文件下载、落库或回复

#### Scenario: 未开始下载的任务直接放弃
- **WHEN** 停机收尾开始且某在途任务尚未进入文件下载阶段
- **THEN** 该任务静默退出，不下载、不落库、不回复

#### Scenario: 下载中的任务被中断并回复取消
- **WHEN** 停机收尾开始且某在途任务正处于文件下载过程中
- **THEN** 系统取消该任务中断下载，清理已产生的临时文件，并向该消息来源回复任务已取消或中断

#### Scenario: 已下载完成的任务完成落库后退出
- **WHEN** 停机收尾开始且某在途任务已完成文件下载（含正在保存与落库的任务）
- **THEN** 系统不中断该任务，等待其完成文件保存、元数据落库并向消息来源回复任务成功后自然退出

#### Scenario: 收尾等待有界兜底
- **WHEN** 在途任务收尾等待超过 10 秒上限
- **THEN** 系统记录说明性日志，放弃等待剩余任务，继续执行停机流程（关闭 websocket 并退出），不无限阻塞

#### Scenario: 空闲时停机不受影响
- **WHEN** 停机流程开始且无任何在途消息任务
- **THEN** 收尾阶段瞬时完成，停机流程与无此机制时一致（关闭 websocket、发送离线通知、以状态码 0 退出）
