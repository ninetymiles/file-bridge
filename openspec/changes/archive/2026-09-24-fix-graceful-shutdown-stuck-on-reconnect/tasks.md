## 1. 修订 BotRunner.shutdown 序列

- [x] 1.1 在 `lib/runner.py` 的 `run()` 方法 shutdown 序列中，第一步改为 `await self.client.stop()`，set SDK 的 `_stop_event`，验证 SDK reconnect 循环 `while not self._stop_event.is_set()` 能正常退出
- [x] 1.2 调整顺序为：`client.stop()` → `runner_task.cancel()` → `await self._runner_task`（带 5s 超时兜底）→ fire-and-forget offline 通知 → `websocket.close()`，验证日志中不再出现 "open connection" 重连记录
- [x] 1.3 在 `request_stop()` 中直接同步 set `self.client._stop_event`（如非 None），不依赖 await 点，验证信号到达后 SDK 立即停止重连

## 2. 二次中断强退

- [x] 2.1 在 `request_stop()` 的 `_is_shutting_down` 短路分支改为 `raise KeyboardInterrupt`，验证第二次 `Ctrl-C` 能让进程立即退出
- [x] 2.2 验证 `start_forever()` 的 `except (KeyboardInterrupt, SystemExit)` 能正确捕获二次中断，进程以非零状态码退出

## 3. 离线通知非阻塞化

- [x] 3.1 在 `lib/runner.py` shutdown 序列中把 `await self.notifier.send_offline_notification()` 改为 `asyncio.create_task(...)` fire-and-forget，验证通知失败/超时不阻塞停机
- [x] 3.2 在 `start_forever()` 退出前 `await asyncio.sleep(0.1)` 给事件循环机会跑通知任务，验证通知能正常发出（如配置了目标）

## 4. 测试覆盖

- [x] 4.1 在 `tests/test_runner.py` 新增测试：mock 一个 client，模拟 `SIGINT` 后验证 `client.stop()` 被调用且 `runner_task.cancel()` 在 `client.stop()` 之后
- [x] 4.2 新增测试：模拟 `_is_shutting_down=True` 时再次调用 `request_stop()`，验证抛出 `KeyboardInterrupt`
- [x] 4.3 新增测试：模拟 offline 通知抛异常，验证 shutdown 序列仍能完成且返回 exit code 0
- [x] 4.4 运行 `uv run pytest` 全量测试，验证无回归

## 5. Phase 2: BotService 解耦（不引入 ASGI）

- [x] 5.1 在 `lib/runner.py` 新增 `BotService` 类（或将 `BotRunner` 重构为 `BotService`），对外暴露 `async def start()` 与 `async def stop()` 两个公开方法，封装 SDK 客户端、Pipeline 与 LifecycleNotifier 的构造与清理
- [x] 5.2 实现 `BotService.start()`：构造 client、Pipeline、LifecycleNotifier，启动 SDK 后台 task，发送 online 通知；处理"已 running 再次调用"幂等性
- [x] 5.3 实现 `BotService.stop()`：复用 Phase 1 修订后的 shutdown 序列（client.stop → cancel → fire-and-forget offline notify → close ws）；处理"已 stopped 再次调用"幂等性
- [x] 5.4 保留同步入口 `run_forever()`（或 `run()` 工厂函数）：以 `asyncio.run` 调用 `BotService.start_and_wait()`，注册 `SIGINT`/`SIGTERM` 信号回调触发 `stop()`，捕获 `KeyboardInterrupt` 完成退出
- [x] 5.5 更新 `app/main.py` 以消费 `BotService` 同步入口，验证 CLI 启动 `uv run python -m app.main` 行为与重构前等价
- [x] 5.6 在 `tests/test_runner.py` 新增测试：验证 `BotService.start()` 重复调用幂等，`BotService.stop()` 重复调用幂等
- [x] 5.7 验证 `BotService` 不引入 ASGI / Uvicorn / FastAPI 依赖（`pyproject.toml` 中无新增相关依赖）
- [x] 5.8 运行 `uv run pytest` 全量测试，验证 Phase 2 重构无回归
