## 1. 配置支持与选项扩展

- [x] 1.1 在配置模块中增加 `NOTIFY_CONVERSATION_ID` 和 `NOTIFY_USER_ID` 参数解析，支持环境变量与命令行参数覆盖，并通过单元测试验证解析优先级
- [x] 1.2 编写针对未配置通知目标场景的单元测试，验证静默标记行为

## 2. 生命周期主动通知器实现

- [x] 2.1 在 `lib/` 下实现 `LifecycleNotifier`，封装基于钉钉 OpenAPI 的上下线消息推送逻辑（群聊与单聊支持）
- [x] 2.2 实现未配置目标的静默跳过策略与网络超时/异常防崩溃保护，并编写测试验证无论发送成功或失败均不抛出异常

## 3. 异步生命周期运行器与信号处理

- [x] 3.1 在 `lib/runner.py` 中实现 `BotRunner`，接管 `asyncio` 事件循环并统一注册 `SIGINT` 与 `SIGTERM` 处理器
- [x] 3.2 实现受控停机流：触发离线通知、关闭 WebSocket、取消后台任务并正常以退出码 0 退出，避免网络错误堆栈
- [x] 3.3 重构 `app/main.py` 入口调用 `BotRunner`，移除原有的 `client.start_forever()`

## 4. 集成验证与端到端测试

- [x] 4.1 编写信号模拟测试（通过 `signal.raise_signal` 或单元测试 mocking），验证触发 `SIGINT` 和 `SIGTERM` 时服务正常停机且退出码为 0
- [x] 4.2 验证容器启动配置与 `docker stop` 行为兼容性，确保不再发生超时强杀
