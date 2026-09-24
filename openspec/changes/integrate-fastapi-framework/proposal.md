## Why

当前项目技术栈规划包含 FastAPI，且容器化部署已有对外暴露 HTTP 端口及健康检查（如 `docker-compose.yml` 中的 `/api/v1/health` 探针注释）的演进诉求。引入 FastAPI 与 Uvicorn ASGI Server 可提供 HTTP 接口服务能力与生产级信号处理，并通过 FastAPI lifespan 钩子复用前序变更（`fix-graceful-shutdown-stuck-on-reconnect`）产出的 `BotService` 异步生命周期协议，实现 HTTP 服务与钉钉长连接服务的统一编排。

## What Changes

- **FastAPI 实例与路由集成**：在 `app/` 中初始化 FastAPI 应用实例，提供基础健康检查接口（`/api/v1/health`）与版本信息接口。
- **基于 Lifespan 钩子消费 BotService**：利用 FastAPI 的 `asynccontextmanager`（lifespan 上下文），在应用启动阶段调用 `await BotService.start()`，在应用停机阶段调用 `await BotService.stop()`。shutdown 序列逻辑由 `fix-graceful-shutdown-stuck-on-reconnect` 变更负责，本变更不重复实现。
- **引入 Uvicorn 作为 ASGI Server**：将 `uvicorn[standard]` 正式声明为依赖，由 Uvicorn 接管主事件循环与 OS 信号处理，触发 FastAPI lifespan 钩子。
- **服务启动与部署命令更新**：支持通过 `uvicorn app.main:app` 运行应用，并相应适配 Dockerfile 与 docker-compose 的运行指令。

## Capabilities

### New Capabilities
- `http-service`: 涵盖 FastAPI 框架的引入、基础 HTTP 端点路由（含健康检查）以及通过 Uvicorn 运行 ASGI 服务的相关规范。

### Modified Capabilities
- `lifecycle-management`: 增加"FastAPI Lifespan 钩子消费 BotService"需求，要求 lifespan 钩子在 startup 阶段调用 `await BotService.start()`、在 shutdown 阶段调用 `await BotService.stop()`，不直接描述 shutdown 序列内部细节（由 `fix-graceful-shutdown-stuck-on-reconnect` 变更负责）。

## Impact

- **运行时架构**：从独立的脚本式 Python 进程演进为 ASGI 驱动的 Web + Stream 综合服务。
- **容器与部署**：激活健康检查探针，支持容器外部通过 HTTP 端口监控机器人状态。
- **依赖管理**：项目中已声明 `fastapi`，需新增 `uvicorn[standard]` 作为 ASGI 服务器并正确配置。
- **依赖变更**：本变更依赖 `fix-graceful-shutdown-stuck-on-reconnect` 变更先行落地 `BotService` 协议，否则 lifespan 钩子无 API 可消费。
