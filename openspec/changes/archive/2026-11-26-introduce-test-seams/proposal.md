# Proposal

## Why

上一轮 `tighten-test-contracts` 清理了「日志作为测试判据」的问题，但测试里还有一批**白盒用例**：它们断言被测对象自己的私有函数、私有属性与内部协作者，导致实现一重构测试就碎，也让生产代码失去演进空间。更关键的是，部分用例靠 `hasattr` 反射和写私有属性 `_http_client` 才能跑起来，说明生产侧缺少显式接缝，被测试的写法掩盖了。

## What Changes

- **删除零信息量断言**（不改变任何覆盖目标）：
  - `test_index_report.test_snapshot_does_not_access_database`（全局替换 `sqlite3.connect`）
  - `test_command_matching` 中对 `embedder.passage_inputs` / `query_inputs` 的断言
  - `test_runner` 的 `logger.warning.called` 与三处 `client.stop.assert_not_awaited()`
  - `test_daily_report_scheduler` 的 `sleeper.calls == [3600]` 与 `asyncio.all_tasks()` 差集反查
  - `test_lifecycle_notifier` 的 `call_args_list[n].args[1] is group_message` 身份断言与「第一条必须是群」的顺序假设
- **改写为黑盒行为断言**：
  - `test_media_file_handler`：入库字段改用真实 `MetadataStore` 读回；媒体元数据行改用真实 EXIF fixture，删除 `patch("app.handlers.message.extract_media_metadata")`
  - `test_command_handler`：引导回复改在 `CommandHandler.handle()` 层断言，不再直接测 `build_guide_reply`、不再 patch `random.choice`
  - `test_lifecycle_notifier`：按内容定位调用（包含快照正文的那一条），不再依赖调用顺序
- **补齐三处生产接缝**（不改行为）：
  - `create_pipeline(...)` 接受可选 `file_downloader`，测试不再写私有 `_http_client`
  - `PipelineHandler` 接受 `warmup_delay`（构造参数，默认 3.0），测试不再 patch 模块内 `ensure_storage_ready`
  - `main._ReviewGate` / `_build_wake_warmup` 提升为公开的 `ReviewGate` / `build_wake_warmup`（仅重命名）
- **明确不做**：不给 `LifecycleNotifier` 引入 `card_sender` 抽象；不改 `test_drain`；不改业务行为、配置或数据结构。

## Capabilities

无。本变更只调整测试写法与构造注入点，没有规格级行为变化，故 `.openspec.yaml` 标记 `skip_specs: true`。

## Impact

- `tests/`：8 个文件，约 20 个用例删除或改写。
- `app/main.py`：`create_pipeline` 增加可选参数；两个私有名改为公开名。
- `app/handlers/message.py`：`PipelineHandler.__init__` 增加 `warmup_delay`，`_dispatch` 传给 `ensure_storage_ready`。
- 无行为、配置、数据库变更；回滚只需还原提交。
