## Why

当前项目技术栈规划包含 FastAPI，且容器化部署已有对外暴露 HTTP 端口及健康检查（如 `docker-compose.yml` 中的 `/api/v1/health` 探针注释）的演进诉求。引入 FastAPI 并通过现代异步生命周期管理器（lifespan）托管钉钉 Stream 机器人，可实现 HTTP 接口服务与钉钉长连接服务的统一编排与协同运行。

## What Changes

- **FastAPI 实例与路由集成**：在 `app/` 中初始化 FastAPI 应用实例，提供基础健康检查接口（`/api/v1/health`）与版本信息接口。
- **基于 Lifespan 的生命周期统一编排**：利用 FastAPI 的 `asynccontextmanager`（lifespan 上下文），在应用启动时拉起钉钉 Stream 客户端后台任务，并在应用停机时执行安全断连与资源回收。
- **服务启动与部署命令更新**：支持通过 Uvicorn ASGI 服务器运行应用（如 `uvicorn app.main:app`），并相应适配 Dockerfile 与 docker-compose 的运行指令。

## Capabilities

### New Capabilities
- `http-service`: 涵盖 FastAPI 框架的引入、基础 HTTP 端点路由（含健康检查）以及通过 Uvicorn 运行 ASGI 服务的相关规范。

### Modified Capabilities
- `lifecycle-management`: 将生命周期的驱动方式从纯脚本手动信号管理演进为兼容由 FastAPI lifespan 容器化统一驱动。

## Impact

- **运行时架构**：从独立的脚本式 Python 进程演进为 ASGI 驱动的 Web + Stream 综合服务。
- **容器与部署**：激活健康检查探针，支持容器外部通过 HTTP 端口监控机器人状态。
- **依赖管理**：项目中已声明 `fastapi`，需确保 `uvicorn` 作为 ASGI 服务器被正式纳入依赖并正确配置。
