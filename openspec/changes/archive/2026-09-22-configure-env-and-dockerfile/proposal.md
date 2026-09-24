## Why

当前 `app/main.py` 要求必须显式传入 `--client_id` 与 `--client_secret` 命令行参数才能启动，不支持自动从 `.env` 环境变量文件读取，在容器与本地多环境部署时不便于统一配置管理。同时 `Dockerfile` 中启动模块路径配置错误（使用了 `:app` ASGI 语法），导致容器无法正常启动。

## What Changes

- **应用配置支持环境变量回退**：`app/main.py` 默认通过 `dotenv` 从环境变量读取 `CLIENT_ID` 与 `CLIENT_SECRET`；若命令行显式提供参数，则优先使用命令行传入的值；若两处皆未提供则友好报错退出。
- **Dockerfile 修正与优化**：
  - 修正容器启动命令为 `CMD ["python", "-m", "app.main"]`。
  - 增加 `ENV PYTHONUNBUFFERED=1` 配置，确保 Python 标准输出和标准错误日志实时刷出至容器日志中。

## Capabilities

### New Capabilities
- `bot-config`: 钉钉机器人凭证与启动配置管理规范，规定环境变量优先回退策略与参数校验。

### Modified Capabilities
<!-- 无现有规范需要修改 -->

## Impact

- 受影响代码：`app/main.py`、`Dockerfile`
- 运行依赖：无需新增依赖，保持 `python-dotenv` 既有依赖
- 容器部署：容器镜像构建后可正常执行启动
