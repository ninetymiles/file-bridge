# Tasks

## 1. 有界反复取消 runner task

- [ ] 1.1 在 `app/core/runner.py` 中以“预算内每 0.1 秒补发一次 `cancel()` + `asyncio.wait(..., timeout=0.1)`”替换 `stop()` 步骤 2 的 `asyncio.wait_for`，并同步重写 `stop()` docstring 的步骤说明；验证：`uv run pytest tests/test_runner.py -k shutdown` 通过，且原有幂等/通知测试不回归。
- [ ] 1.2 新增 `tests/test_runner.py` 用例：runner task 捕获首次 `CancelledError` 后进入 10 秒睡眠（模拟 SDK 重连前睡眠），验证：`request_stop()` 后 `start_and_wait()` 在 2 秒内返回、`_runner_task.cancelled()` 为真、无 `TimeoutError` 泄漏。

## 2. 二次信号强退

- [ ] 2.1 在 `request_stop()` 的“已在停机中”分支改为先记录 WARNING 并 flush 日志处理器，再 `os._exit(130)`；验证：新增用例用 patch 替换 `os._exit`，断言被调用一次且参数为 130。
- [ ] 2.2 调整既有 `test_request_stop_raises_on_second_signal` 的断言，从“抛出 `KeyboardInterrupt`”改为“终止进程并返回 130”；验证：`uv run pytest tests/test_runner.py` 全绿。

## 3. 容器停止宽限期

- [ ] 3.1 在 `docker-compose.yml` 的 `bridge` 服务增加 `stop_grace_period: 20s`，并在文件内注释说明其必须大于 drain（10 秒）加取消预算（1 秒）；验证：`docker compose config` 输出包含 `stop_grace_period: 20s`。

## 4. 规范与集成验证

- [ ] 4.1 运行 `openspec validate fix-single-ctrl-c-shutdown --strict`，确认 delta spec 无告警（MODIFIED 块名与既有需求标题一致）。
- [ ] 4.2 在具备 `.env` 凭证的环境手工冒烟：启动 `uv run python -m app.main`，单次 `Ctrl-C` 后验证：2 秒内出现 `Graceful shutdown completed successfully.`、退出码 0、无 Traceback、无 `Task was destroyed but it is pending!` 日志。
- [ ] 4.3 在容器环境执行 `docker compose up -d` 后 `docker stop file-bridge`，验证：容器在 12 秒内以退出码 0 结束，容器日志包含 `Graceful shutdown completed successfully.`，且无 `SIGKILL`。

## Workflow follow-up

- 评审通过后归档变更，使 `lifecycle-management` 的 MODIFIED 需求同步到主规范。
- 归档后核对主规范中“有界等待后进程退出”的旧表述已被替换。
