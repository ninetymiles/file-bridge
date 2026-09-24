## Context

当前机器人使用纯 Stream 客户端（WebSocket 长连接），应用入口在 `app/main.py`。动机见 proposal.md。

## Goals / Non-Goals

**Goals:**
- 实现 CLI 参数与环境变量的优雅回退与非空校验。
- 保证 Docker 容器以合法的模块路径直接启动应用入口并实时刷新日志。

**Non-Goals:**
- 引入 FastAPI 或其他 HTTP 端口监听（当前阶段保持纯 Stream 客户端应用形态）。
- 重构 `docker-compose.yml` 中的 healthcheck（待后续整体规划）。

## Decisions

### 1. argparse 配合环境变量默认值
- **决策**：在 `argparse.ArgumentParser.add_argument` 中直接使用 `default=os.getenv('CLIENT_ID')` / `default=os.getenv('CLIENT_SECRET')`，并将 `required=True` 移除；在解析完成后判断 `options.client_id` 与 `options.client_secret` 是否有值，缺失时调用 `parser.error(...)` 报错退出。
- **考量与对比**：
  - 相比在解析后手动 `options.client_id or os.getenv(...)`，使用 `default=...` 可以在 `--help` 提示中更直观，同时统一由 `parser` 报出参数错误并退出。

### 2. Dockerfile 修正运行命令与缓冲设置
- **决策**：
  - 将 `CMD ["python", "-m", "app.main:app"]` 改为 `CMD ["python", "-m", "app.main"]`。
  - 增加 `ENV PYTHONUNBUFFERED=1`。
- **考量**：
  - Python 标准模块启动语法为 `python -m <module>`，`:app` 仅为 uvicorn/gunicorn 所用；
  - 容器环境无交互式 TTY，设置 `PYTHONUNBUFFERED=1` 可以避免标准输出和标准错误被缓存，确保 `docker logs` 实时显示日志。

## Risks / Trade-offs

- [Risk] 当前 `docker-compose.yml` 包含 HTTP 8000 healthcheck，若用 Compose 启动会判定为 unhealthy。
  → Mitigation: 用户后续会自行调整/注释 compose 配置，非本次变更范围。
