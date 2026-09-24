## Context

项目 `pyproject.toml` 中已包含 `fastapi>=0.141.1`，但当前入口 `app/main.py` 仍为普通的单体脚本调用模式。引入 FastAPI 后，应用将由 ASGI 服务器（Uvicorn）接管主事件循环与系统信号（SIGINT/SIGTERM）。

## Goals / Non-Goals

**Goals:**
- 提供 `FastAPI` 实例作为主应用入口 `app.main:app`。
- 实现 `/api/v1/health` 端点，为 Docker / K8s 健康检查提供探针支持。
- 使用 `lifespan(app: FastAPI)` 上下文管理器无缝衔接前序实现的 `BotRunner` / `BotService`，实现一键启动与停机。

**Non-Goals:**
- 本次暂不开发复杂的业务 HTTP 接口（如向钉钉发送自定义业务文件的开放 API），留待后续业务变更逐步规划。

## Decisions

### 1. 生命周期委托给 FastAPI Lifespan
- **实现方式**：
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      bot_service = create_bot_service()
      await bot_service.start()
      yield
      await bot_service.stop()
  ```
- **收益**：避免手工编写信号监听代码，复用 Uvicorn 自带的生产级优雅停机机制。

### 2. 路由结构设计
- 采用 APIRouter 风格，基础探针放在 `/api/v1` 路径下，方便后续功能扩展。

## Risks / Trade-offs

- **[Risk] Uvicorn 依赖尚未直接声明在 pyproject.toml 中**
  → **Mitigation**：需在实施时将 `uvicorn[standard]` 添加至 `pyproject.toml` 依赖项。
