# Proposal

## Why

当前停机流程在真实 SDK 下无法保证有界退出：一次 `Ctrl-C`（或容器里的单个 `SIGTERM`）之后，进程仍可能卡住 15 秒以上，必须再按 2~3 次 `Ctrl-C`，或等待 Docker 在 10 秒宽限期后发 `SIGKILL` 强杀。根因是 `asyncio.wait_for(self._runner_task, timeout=1.0)` 的超时并不能让调用方在 1 秒后返回，而 SDK 0.24.3 会把 `CancelledError` 当作网络异常吞掉、睡眠 10 秒后重连，导致 runner task 永远不结束，`asyncio.run` 的 teardown 也一直等待它。

## What Changes

- `BotService.stop()` 的 runner task 收尾从"cancel 一次 + `wait_for` 1 秒"改为"在 1 秒预算内反复 cancel，每轮用 `asyncio.wait(..., timeout=)` 有界等待"。
  - `asyncio.wait` 到期即返回，不依赖被等待任务的完成，也不取消调用方任务。
  - 每轮补发 `cancel()`，使某一次必然落在 SDK 的 `except` 块内 `sleep(10)` 上并终止 `start()`。
- 二次停机信号改为直接终止进程（先 flush 日志，再以 130 退出），不再依赖 `KeyboardInterrupt` 穿过 `asyncio.run` 的 teardown——后者同样会被 SDK 的重连循环阻塞。
- 容器停机预算：`docker-compose.yml` 为 `bridge` 服务增加 `stop_grace_period`，使其大于 drain 上限（10 秒）加收尾耗时，避免优雅停机被 Docker 默认 10 秒宽限期截断为 `SIGKILL`。
- 同步修正 `lifecycle-management` 规范中"有界等待后进程退出、从根本上阻止重连"的表述，明确退出前提是 runner task 在预算内真正结束。
- 新增测试：runner task 吞掉首次取消时，停机仍在预算内结束且任务进入 cancelled 状态。

## Capabilities

### New Capabilities

无。本变更只修正既有停机行为。

### Modified Capabilities

- `lifecycle-management`: 修改"信号拦截与优雅停机"需求，明确有界退出的实现前提是取消动作可重复且等待不阻塞调用方，并明确二次信号为立即可终止进程。

## Impact

- 代码：`app/core/runner.py`（`stop()` 的取消策略、`request_stop()` 的二次信号处理）。
- 测试：`tests/test_runner.py`（新增"吞掉取消"场景，调整二次信号断言）。
- 配置：`docker-compose.yml`（`stop_grace_period`）。
- 规范：`openspec/specs/lifecycle-management/spec.md`。
- 依赖：不修改第三方 SDK，不新增依赖。
