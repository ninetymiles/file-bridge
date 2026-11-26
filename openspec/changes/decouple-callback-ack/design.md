# Design

## Context

动机见 [proposal.md](proposal.md) - "Why"，行为契约见 [specs/message-pipeline/spec.md](specs/message-pipeline/spec.md)。

现状与约束：

- SDK 的确认时机不可配置：`CallbackHandler.raw_process` 在 `process()` 返回后才构造 ack，`DingTalkStreamClient.route_message` 随后才写回 websocket。
- 确认报文的数据体不被平台使用（回复走 `sessionWebhook`），因此确认可以与回复彻底解耦。
- `PipelineHandler.process()` 当前同步跑完整条 `_dispatch()`（预热、下载、去重、落盘、元数据、点评窗口、回复），并把 SDK 任务注册进 `_active_tasks` 供停机 drain 使用。
- 平台实测在推送后 T+60s 重投未确认的机器人消息；两次冷盘多图事故的重投时间分别为 T+59.99s 与 T+59.94s，而 T+60s 内完成确认的两次冷盘消息均未重投。
- 回复内容由处理器产出的意图决定，Dispatcher 只负责层级裁决、合并发送与 `after_reply` 门闩；这些契约不变。

## Goals / Non-Goals

**Goals:**

- 确认延迟与处理时长解耦：确认只发生在受理阶段。
- 停机收尾、异常可观测性、回复合并与点评顺序等既有契约保持原样。
- 改动集中在 Dispatcher 的受理层，处理器与业务链路零改动。

**Non-Goals:**

- 不做 `messageId` 幂等门；平台侧偶发重投仍可能产生一次重复回复。
- 不调整存储预热策略、点评 15 秒合并窗口、两段式回复规则。
- 不修改 SDK、回复文案、配置项或数据库结构。

## Decisions

### D1：受理即确认，处理链改为后台任务

`process()` 在完成 `_draining` 准入判断后，创建一个后台任务执行 `_dispatch(callback)`，随后立即返回 `AckMessage.STATUS_OK`。

时序：

```
平台推送 --> process(): 准入判断 -> create_task(_dispatch) -> 立即 ACK
                                     |
                                     +--> 预热 --> 处理链 --> 回复（sessionWebhook）
```

备选方案与取舍：

| 方案 | 结论 |
|---|---|
| 保持同步，只压缩处理耗时 | 否决：冷盘探针单次实测 48~57 秒，无法稳定进入 60 秒窗口 |
| 在 SDK 层提前 ack | 否决：SDK 无回调钩子，需 fork 或替换 SDK |
| 只加 `messageId` 幂等门 | 本次未选：能消除重复回复，但不消除确认超时与重投带来的重复下载 |

### D2：后台任务纳入现有在途集合

后台任务加入 `_active_tasks`，完成回调负责摘除。这样 `begin_drain()` 与 `drain_active_tasks()` 的语义不需要改：准入关闭此前已受理的任务继续跑完，等待仍有界。

备选方案：新增独立的“处理中任务”集合 → 否决，两套集合并存会让停机逻辑产生重复职责。

### D3：后台异常显式取回并记录

同步链路下异常由 SDK 的 `background_task` 捕获并记录；改为后台任务后该保护失效，因此在任务完成回调中检查 `task.exception()` 并记录（含异常类型与截断后的消息），避免 "Task exception was never retrieved" 与静默丢失。记录是排障手段，不作为测试判据：测试通过「任务已摘除、进程继续服务」验证取回行为。

备选方案：在后台协程内部整体 `try/except` → 效果等价，但会把兜底逻辑混进业务链路；放在完成回调更贴合“准入层负责投递”的单一职责。

### D4：测试用汇合助手，不新增生产 API

36 处测试调用依赖“`process()` 返回时回复已产生”（`test_integration.py` 20、`test_media_review_reply.py` 15、`test_pipeline.py` 1）。统一改为 `process_and_wait(pipeline, callback)`（测试内助手：先 `process`，再 `drain_active_tasks`），不为了测试在生产代码里新增 `wait_idle()` 之类的方法。

备选方案：让 `process()` 在测试模式下等待 → 否决，生产与测试路径分叉，契约测试失真。

### D5：新增确认时效契约测试

用会阻塞的假处理器验证：`process()` 在固定短阈值内返回，且回复在汇合点之后才出现。该测试锁定“确认不等待处理”的行为，而不是锁定具体实现。

## Risks / Trade-offs

- [进程崩溃导致已确认消息丢失] → 确认提前后平台不再重投；崩溃时该消息的文件不会落盘。缓解：归档阶段本就不被中断，优雅停机仍走 drain；接受该残余风险（此前也无法保证崩溃前完成保存）。
- [事件循环被同步 I/O 阻塞仍会拖慢确认] → 预热探针在 `asyncio.to_thread` 中执行，`storage-warmup` 已要求「唤醒等待不阻塞事件循环」；确认路径本身只做准入判断与建任务，不触碰磁盘。
- [测试汇合点遗漏导致偶发失败] → 统一使用 `process_and_wait` 助手，并新增确认时效测试覆盖最容易漏测的慢处理器路径。
- [重投仍可能因网络抖动发生] → 本次不做幂等，重复回复概率显著降低但非零；已在 proposal 中声明为非目标。

## Migration Plan

- 无数据结构、配置或接口变更，单次部署生效。
- 回滚：还原提交即可，无残留状态。
- 上线后观察验证：冷盘多图消息的日志中，同一条消息的 `Received group message` 只出现一次，且不再出现第二次下载与「文件已存在，请勿重复发送」。

## Open Questions

无。
