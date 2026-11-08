# Spec Delta

## MODIFIED Requirements

### Requirement: 信号拦截与优雅停机
系统 SHALL 拦截并统一处理操作系统的中断信号（`SIGINT`）与终止信号（`SIGTERM`），执行受控的停机流程并正常退出。停机序列 SHALL 通过重复取消 SDK 运行任务并关闭 websocket 终止长连接。对运行任务的等待 SHALL 是有界的（不超过 1 秒），且每次等待 MUST NOT 阻塞调用方任务的恢复——预算耗尽后调用方 SHALL 继续执行后续停机步骤。系统 SHALL NOT 依赖 SDK 的停止标志接口：当前锁定的 dingtalk-stream 0.24.3 不提供 `stop()` 方法与 `_stop_event`。停机流程 SHALL NOT 等待 SDK 在捕获 `CancelledError` 后的重连循环。

#### Scenario: 收到终端中断信号 SIGINT
- **WHEN** 用户在控制台触发一次 `Ctrl-C` 产生 `SIGINT`
- **THEN** 系统记录停机日志，重复取消 SDK 运行任务直至其结束或预算耗尽，关闭底层网络连接，并在不超过 1 秒的取消预算内完成停机，不抛出未捕获异常堆栈，以状态码 0 退出

#### Scenario: 收到容器停止信号 SIGTERM
- **WHEN** 容器管理系统（如 `docker stop`）向主进程发送一次 `SIGTERM`
- **THEN** 系统执行与 SIGINT 相同的取消与断开连接流程，在不超过 1 秒的取消预算内完成停机，并在部署配置的停止宽限期内以状态码 0 正常退出

#### Scenario: 优雅停机期间的二次中断强退
- **WHEN** 优雅停机流程已启动（首次 `SIGINT`/`SIGTERM` 已处理）后用户再次触发 `Ctrl-C`
- **THEN** 系统 SHALL 立即终止进程并以非零状态码退出，不再继续执行未完成的清理步骤，确保用户始终可强制终止进程

#### Scenario: 停机序列避免 SDK 自动重连
- **WHEN** 优雅停机开始且 SDK 运行任务被取消
- **THEN** 系统 SHALL 持续补发取消，直到该任务结束或取消预算耗尽；即使 SDK 将 `CancelledError` 视为网络异常并计划固定睡眠后重连，进程 SHALL NOT 等待该重连循环，重连不实际发生

#### Scenario: SDK 吞掉首次取消
- **WHEN** SDK 运行任务捕获首次取消后继续运行（进入重连前的固定睡眠）
- **THEN** 系统 SHALL 在剩余预算内再次取消该任务，使其在预算内结束，停机流程继续推进且不出现重复的停机请求日志
