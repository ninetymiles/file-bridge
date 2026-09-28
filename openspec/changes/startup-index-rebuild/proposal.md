## Why

文件元数据索引在运行期间可能因外部归档、手动删除等变得陈旧——磁盘上已不存在的文件仍留有 SQLite 记录。当前只有用户主动发送"重建索引"聊天指令才能清理，属于被动维护。在服务启动、SDK 连接之前自动执行一次索引重建，可保证每次运行开始时索引与磁盘一致，且不延迟消息接收。

## What Changes

- 在 `main()` 中构造 `MetadataStore` 实例后、调用 `runner.run_forever()` 之前，调用 `metadata_store.rebuild_index()`，在 SDK 连接之前完成索引重建。
- 重建完成后通过 `logger.info` 打印清理记录数和剩余记录数，不通过机器人发送通知。
- 将 `MetadataStore` 的创建从 `create_pipeline()` 提取到 `main()`，`create_pipeline()` 改为接收已构造的 `metadata_store` 参数。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `file-indexing`: 新增"启动时自动重建索引"需求——服务启动时在 SDK 连接之前自动执行索引重建，仅在控制台打印 INFO 日志，不发送机器人通知。

## Impact

- 生产代码：`app/main.py`（`main()` 新增 `MetadataStore` 创建与 `rebuild_index()` 调用，`create_pipeline()` 签名改为接收 `metadata_store`）。
- 规范：`file-indexing` spec 新增一条 ADDED 需求，不修改现有"重建索引"维护指令需求。
- 依赖与对外 API：无变化；`MetadataStore.rebuild_index()` 方法已存在，返回 `(cleaned_count, remaining_count)`。
- 测试：新增对 `main()` 启动流程中索引重建行为的单元测试。
