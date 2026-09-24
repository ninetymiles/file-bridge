## 1. 依赖与基础路由搭建

- [ ] 1.1 在 `pyproject.toml` 中添加 `uvicorn` 依赖，并通过 `uv sync` 验证环境同步
- [ ] 1.2 在 `app/main.py` 中初始化 `FastAPI` 实例并编写 `/api/v1/health` 健康检查接口，使用 TestClient 编写单元测试验证返回 200

## 2. Lifespan 钩子消费 BotService

- [ ] 2.1 在 `app/main.py` 中实现 `@asynccontextmanager lifespan(app: FastAPI)`，startup 阶段调用 `await create_bot_service().start()`，shutdown 阶段在 `finally` 块调用 `await app.state.bot_service.stop()`，验证随着应用启停正确拉起和回收 Stream 客户端（依赖 `fix-graceful-shutdown-stuck-on-reconnect` Phase 2 已落地）
- [ ] 2.2 编写单元测试覆盖 lifespan 钩子：mock `BotService` 验证 `start()` 在 startup 阶段被调用、`stop()` 在 shutdown 阶段被调用且至少执行一次（idempotent）

## 3. 部署与容器配置更新

- [ ] 3.1 更新 `Dockerfile` 的默认启动命令为 `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`
- [ ] 3.2 启用 `docker-compose.yml` 中的健康检查探针配置并进行本地容器化验证
