## 1. 应用凭证加载与参数解析

- [x] 1.1 修改 `app/main.py` 导入 `os` 并在 `define_options` 中配置 `default=os.getenv('CLIENT_ID')` 与 `default=os.getenv('CLIENT_SECRET')`，移除 `required=True`
- [x] 1.2 在 `define_options` 中增加空值校验，当缺少 client_id 或 client_secret 时调用 `parser.error` 报错退出
- [x] 1.3 验证凭证优先级：分别验证无参数带 .env 启动、带命令行参数覆盖启动、无凭证抛错退出的行为

## 2. Dockerfile 配置修正

- [x] 2.1 修改 `Dockerfile` 中的启动命令为 `CMD ["python", "-m", "app.main"]`
- [x] 2.2 在 `Dockerfile` 中添加 `ENV PYTHONUNBUFFERED=1`
- [x] 2.3 验证 Docker 构建或运行配置语法无误
