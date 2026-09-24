## Context

项目 `pyproject.toml` 中已包含 `fastapi>=0.141.1`，但当前入口 `app/main.py` 仍为普通的单体脚本调用模式。引入 FastAPI 后，应用将由 ASGI 服务器（Uvicorn）接管主事件循环与系统信号（SIGINT/SIGTERM）。

前序变更 `fix-graceful-shutdown-stuck-on-reconnect` 产出 `BotService` 类（对外暴露 `async start()` / `async stop()`，封装 SDK/Pipeline/Notifier 的初始化与修订后的 shutdown 序列）。本变更负责消费该协议。

## Goals / Non-Goals

**Goals:**
- 提供 `FastAPI` 实例作为主应用入口 `app.main:app`。
- 实现 `/api/v1/health` 端点，为 Docker / K8s 健康检查提供探针支持。
- 在 FastAPI lifespan 钩子里消费 `BotService.start()` / `stop()`，复用 Uvicorn 自带的生产级优雅停机机制。
- 声明 `uvicorn[standard]` 为运行时依赖，由 Uvicorn 触发 lifespan 钩子。

**Non-Goals:**
- 本次暂不开发复杂的业务 HTTP 接口（如向钉钉发送自定义业务文件的开放 API），留待后续业务变更逐步规划。
- 不修改 `BotService` 内部的 shutdown 序列逻辑（由 `fix-graceful-shutdown-stuck-on-reconnect` 负责）。
- 不实现 CLI 脚本与 ASGI 双入口的兼容策略（CLI 脚本继续由前序变更保留）。

## Decisions

### 1. Lifespan 钩子作为 BotService 消费者
- **实现方式**：
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      bot_service = create_bot_service()
      await bot_service.start()           # 协议 API，来自前序变更
      app.state.bot_service = bot_service
      try:
          yield
      finally:
          await bot_service.stop()       # shutdown 序列已被前序变更修对
  ```
- **为何这样设计**：lifespan 钩子只是 BotService 协议的一个调用方；shutdown 序列的具体顺序（先 `client.stop()` 再 cancel 再 fire-and-forget offline notify）由 `fix-graceful-shutdown-stuck-on-reconnect` 的设计决策规定，本变更不重复定义、避免再次写错顺序。
- **错误处理**：`start()` 抛异常时 lifespan 进入 failed startup，Uvicorn 不会调 `stop()`；`stop()` 内部已是 idempotent（前序变更保证），lifespan `finally` 块可安全重复调用。

### 2. 路由结构设计
- 采用 APIRouter 风格，基础探针放在 `/api/v1` 路径下，方便后续功能扩展。

### 3. Uvicorn 依赖与启动命令
- 在 `pyproject.toml` 中添加 `uvicorn[standard]` 作为运行时依赖。
- Dockerfile / docker-compose 默认启动命令改为 `uvicorn app.main:app --host 0.0.0.0 --port 8000`。
- 配置 Uvicorn 的 `--timeout-graceful-shutdown`（推荐 10s），与 SDK reconnect 退出 + offline 通知 fire-and-forget 的总时长匹配。

## Risks / Trade-offs

- **[Risk] Uvicorn 依赖尚未直接声明在 pyproject.toml 中**
  → **Mitigation**：在实施任务 1.1 中显式添加 `uvicorn[standard]`，并通过 `uv sync` 验证环境同步。

- **[Risk] BotService 协议尚未落地**
  → **Mitigation**：本变更依赖 `fix-graceful-shutdown-stuck-on-reconnect` Phase 2 完成。实施前需先确认前序变更已归档；若前序变更遇到阻塞，本变更需等待或调整 lifespan 钩子的实现。

- **[Trade-off] 单一进程同时跑 HTTP 与长连接**
  → ASGI 进程内同时运行 Uvicorn HTTP 处理与钉钉 Stream 后台 task，CPU/IO 共享。当前规模下可接受；未来如需独立伸缩，可拆为双进程 + 共享状态，由后续变更规划。
