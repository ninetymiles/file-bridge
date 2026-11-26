# Tasks

## 1. Dispatcher 受理层改造

- [ ] 1.1 修改 `PipelineHandler.process()`：保留 `_draining` 准入判断后创建后台任务执行 `_dispatch(callback)`，把任务加入 `_active_tasks`，并立即返回 `AckMessage.STATUS_OK`；验证：新增单测让处理器阻塞 2 秒，断言 `process()` 在 50ms 内返回
- [ ] 1.2 为后台任务注册完成回调：从 `_active_tasks` 摘除，并取回异常（记录由实现决定，测试不依赖日志）；验证：注入抛异常的处理器后，`process()` 仍立即返回 OK，`drain_active_tasks()` 能在超时内返回（证明任务已摘除），随后另一条消息仍能正常处理并回复
- [ ] 1.3 适配 `tests/test_drain.py` 中三处创建任务句柄的用例（下载取消、归档跑完、超时放弃），改为观察 `_active_tasks` 中的派发任务；验证：`uv run pytest tests/test_drain.py` 全部通过，且仍覆盖「准入拒绝」「下载取消」「归档跑完」「超时放弃」四种行为

## 2. 测试汇合与回归

- [ ] 2.1 在 `tests/conftest.py` 增加 `process_and_wait(pipeline, callback)` 助手（先 `process`，再 `drain_active_tasks`）；验证：至少一个测试改用该助手并通过
- [ ] 2.2 替换 `tests/test_integration.py`（20 处）、`tests/test_media_review_reply.py`（15 处）、`tests/test_pipeline.py`（1 处）中共 36 处 `process()` / `_send()` 调用为汇合助手；验证：`uv run pytest tests/test_integration.py tests/test_media_review_reply.py tests/test_pipeline.py` 全部通过
- [ ] 2.3 新增重投场景回归测试：一条含 3 张图片的 `richText` 消息在慢处理器下只产生一次处理与一条合并回复，且确认先于回复完成；验证：测试断言 `process()` 立即返回、汇合后回复数量为 1、回复中不出现第二次「文件已存在，请勿重复发送」

## 3. 契约校验

- [ ] 3.1 核对实现与 delta spec 的四类场景（冷盘多图确认、处理耗时、停机收尾、后台异常）逐条对应；验证：`openspec validate "decouple-callback-ack"` 通过，且每个场景都有对应测试或既有测试覆盖说明
- [ ] 3.2 运行全量测试；验证：`uv run pytest` 全部通过

## Workflow follow-up

- 部署后观察冷盘多图消息日志：同一条消息的 `Received group message` 只出现一次，且不再出现第二次下载与「文件已存在」回复。
- 评审满足后归档该变更。
