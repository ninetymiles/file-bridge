## Context

当前应用入口 `app/main.py` 直接调用 `dingtalk-stream` SDK 的 `client.start_forever()`。底层 SDK 0.24.3 在捕获中断信号时将 `CancelledError` 视为普通网络异常，在内部 sleep 10 秒重试，且外层带有无条件 `time.sleep(3)`，造成 Ctrl-C 抛出未捕获异常并需要多次强制中断。此外，Docker 容器内以 PID 1 运行的 Python 进程若不显式注册 `SIGTERM` 处理器，会被直接忽略导致 10 秒超时强杀。

## Goals / Non-Goals

**Goals:**
- 提供集中式的异步生命周期管理器，统一拦截 `SIGINT` 与 `SIGTERM` 信号。
- 在服务关闭时主动断开底层连接并优雅退出，消除无用异常堆栈输出。
- 支持基于配置的钉钉上下线主动通知（群聊或单聊），未配置时干净静默。
- 将生命周期编排与具体业务处理器（如 `CalcBotHandler`）解耦。

**Non-Goals:**
- 不修改 `third-party/` 下的第三方源码，所有运行逻辑在项目自身代码中适配。
- 不引入重型消息队列或分布式状态监控，仅基于钉钉 OpenAPI 进行轻量状态通知。

## Decisions

### 1. 采用独立的 LifecycleRunner 管理事件循环与信号
- **方案选择**：在 `lib/runner.py` 中封装 `BotRunner`，由其接管 `asyncio` 事件循环和信号处理，放弃调用有缺陷的 `client.start_forever()`。
- **信号处理策略**：通过 `loop.add_signal_handler(sig, ...)` 注册 `signal.SIGINT` 与 `signal.SIGTERM`。捕获信号后，触发 `asyncio.Event` 停止标志位，使客户端平滑停止。
- **替代方案考虑**：
  - *修改第三方源码*：侵入性强，难以通过包管理维护，不可取。
  - *外层只做 try-except KeyboardInterrupt*：无法拦截 Docker 容器的 `SIGTERM`，也无法解决 SDK 内部 10s sleep 的问题。

### 2. 生命周期主动通知设计
- **接口选择**：通过 `dingtalk_stream` 现有的 `reply_specified_group_chat` 或 `reply_specified_single_chat`，使用 `ChatbotHandler.reply_markdown(...)` 配合 OpenAPI 发送上线与离线通知。
- **配置与静默处理**：
  - 参数支持：环境变量 `NOTIFY_CONVERSATION_ID` / `NOTIFY_USER_ID`，及对应命令行参数。
  - 静默原则：未配置任何通知目标时，仅输出 `DEBUG` 级别日志，不做网络调用，不阻断流程。
  - 容错保护：通知发送失败时记录 `WARNING` 日志，绝不允许因通知失败影响核心停机或启动。

```text
+-------------------------------------------------------+
|                      BotRunner 运行流                  |
+-------------------------------------------------------+
| 1. register_signal_handlers(SIGINT, SIGTERM)          |
| 2. client.pre_start()                                 |
| 3. await notifier.send_online_notification()          |
| 4. runner_task = asyncio.create_task(client.start())  |
| 5. await stop_event.wait()                            |
| 6. await notifier.send_offline_notification()         |
| 7. client.websocket.close() & runner_task.cancel()    |
| 8. clean exit (code 0)                                |
+-------------------------------------------------------+
```

## Risks / Trade-offs

- **[Risk] SDK 内部的 websocket 引用在启动初期为 None**
  → **Mitigation**：在执行 stop 逻辑时增加空值与连接状态判断，先取消 `client.start()` 对应 Task，再清理残留 socket。
- **[Risk] 停机期间发送离线通知因网络阻塞延缓退出**
  → **Mitigation**：为离线通知请求添加短超时保护（如 3-5 秒），防止阻塞优雅退出流程。
- **[Risk] Windows 平台不支持 loop.add_signal_handler**
  → **Mitigation**：开发和部署目标为主机 macOS / Linux 容器；若在 Windows 环境则优雅降级为 try/finally 机制。
