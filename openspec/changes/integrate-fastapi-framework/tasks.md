## 1. 依赖与基础路由搭建

- [ ] 1.1 在 `pyproject.toml` 中添加 `uvicorn` 依赖，并通过 `uv sync` 验证环境同步
- [ ] 1.2 在 `app/main.py` 中初始化 `FastAPI` 实例并编写 `/api/v1/health` 健康检查接口，使用 TestClient 编写单元测试验证返回 200

## 2. Lifespan 与机器人服务生命周期打通

- [ ] 2.1 将机器人服务封装为可异步 `start()` 和 `stop()` 的 `BotService`
- [ ] 2.2 在 FastAPI 的 `lifespan` 上下文中集成 `BotService`，验证随着应用启停正确拉起和回收 Stream 客户端

## 3. 部署与容器配置更新

- [ ] 3.1 更新 `Dockerfile` 的默认启动命令为 `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`
- [ ] 3.2 启用 `docker-compose.yml` 中的健康检查探针配置并进行本地容器化验证
