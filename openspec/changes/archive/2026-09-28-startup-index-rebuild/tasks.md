## 1. 提取 MetadataStore 创建并接入索引重建

- [x] 1.1 重构 `app/main.py`：将 `MetadataStore(output_dir=...)` 的创建从 `create_pipeline()` 内部提取到 `main()` 中，`create_pipeline()` 签名改为接收 `metadata_store` 参数；验证：`uv run pytest -q` 全量通过，确认 pipeline 与 handler 注入不受影响

## 2. 启动时索引重建与日志

- [x] 2.1 在 `main()` 中 `create_pipeline()` 之后、`runner.run_forever()` 之前，调用 `metadata_store.rebuild_index()` 获取 `(cleaned_count, remaining_count)`，通过 `logger.info` 输出格式如 `Index rebuilt: cleaned %d records, %d records remain`；验证：手动检查日志输出格式，确认在 SDK 连接之前执行
- [x] 2.2 新增单元测试覆盖启动时索引重建行为：mock `MetadataStore.rebuild_index` 返回 `(3, 10)`，调用 `main()` 启动流程（mock SDK 避免 websocket 连接），断言 `rebuild_index` 被调用且 `logger.info` 包含清理数与剩余数；验证：`uv run pytest tests/test_startup_index_rebuild.py -q` 通过

## 3. 校验

- [x] 3.1 运行 `uv run pytest -q` 全量测试通过
- [x] 3.2 运行 `openspec validate startup-index-rebuild --strict` 确认工件合法
- [x] 3.3 真实环境人工确认：启动时控制台输出 INFO 日志显示索引重建结果，之后才连接 SDK 和发送上线通知
