## Why

当前应用在本地终端运行时，按 `Ctrl-C` 无法正常退出，反而被 DingTalk Stream SDK 捕获误判为网络错误并陷入重试，需要多次强制中断才能通过未捕获异常退出；同时在 Docker 容器环境下缺乏对 `SIGTERM` 信号的显式捕获与优雅停机支持，导致 `docker stop` 超时被强制强杀。此外，系统缺乏服务生命周期状态的主动通知机制，运维人员无法及时获知机器人服务的上下线状态。

## What Changes

- **优雅停机与信号管理**：同时监听并处理 `SIGINT`（Ctrl-C）和 `SIGTERM`（Docker 停机）信号，拦截中断事件，友好打印停机日志，主动关闭底层连接并平稳退出（退出码 0），消除异常堆栈输出。
- **生命周期通知配置**：扩展启动配置，支持通过环境变量或命令行参数指定通知目标（群聊 `conversation_id` 或单聊 `user_id`）。
- **上下线主动通知**：在应用成功启动建立连接后发送“上线”通知；在接收到停机信号开始清理时发送“离线”通知；若未配置通知目标，则保持静默跳过，不影响正常启动与退出流程。

## Capabilities

### New Capabilities
- `lifecycle-management`: 涵盖进程优雅停机（SIGINT/SIGTERM 信号处理与连接清理）以及基于配置的上线与离线主动通知能力。

### Modified Capabilities
- `bot-config`: 扩展凭证与运行配置，增加通知目标参数（`NOTIFY_CONVERSATION_ID` 和 `NOTIFY_USER_ID`）的环境变量与命令行选项支持。

## Impact

- **代码模块**：在 `app/main.py` 中引入生命周期管理和信号监听，在 `lib/` 中提供生命周期运行器和主动通知工具函数。
- **依赖与 SDK**：不修改第三方依赖，基于当前 `dingtalk-stream` 现有接口以异步受控 Task 方式运行，并通过 OpenAPI 凭证机制发送通知。
- **容器与运维**：提升容器在 `docker stop` 时的响应速度与优雅度，避免非正常退出。
