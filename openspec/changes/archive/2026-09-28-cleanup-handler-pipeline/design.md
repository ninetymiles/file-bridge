## Context

See proposal.md - Why。当前 `PipelineHandler`（`app/handlers/message.py`）在一个类内混合了三项职责：消息分发（`process`/`_dispatch`）、接收日志（`_log_received_message`，87 行）、优雅关闭排水（`_draining`/`_active_tasks` 及四个方法）。`MediaFileHandler` 通过 `pipeline.is_draining()` 与 `pipeline.mark_download_done()` 反向感知关闭状态，且 `mark_download_done` 必须在"下载完成后、任意 await 前"调用，契约脆弱。处理链末尾的 `CalcBotFallbackHandler` 是早期 calc bot 演示残留，与文件桥业务无关。`observability` spec 以接口契约形式规定日志精确格式，迫使测试断言诊断日志。

## Goals / Non-Goals

**Goals:**

- 移除 `CalcBotFallbackHandler` 整条链路。
- 采用 **task 链 + handler 自治取消** 架构：排水退化为纯机制（关入口 + 通知 handler 取消可中断工作 + 等待全部 SDK task 结束），各 handler 自行管理可中断 task 的生命周期与取消策略；删除 `mark_download_done` 时序契约。
- 删除未使用的 `add_handler`。
- 改写 `observability` spec，移除日志格式契约。

**Non-Goals:**

- 不改动接收日志 `_log_received_message` 的实现与输出（行为不变，仅 spec 不再约束）。
- 不触碰 `support-group-chat-messages` 在途变更（其 design/tasks 中以加法 handler 为锚点的内容待存档后另行修订）。
- 不拆分 `handlers/message.py` 为多文件（单文件优先）。
- 不为不可中断阶段创建子 task：不可中断工作内联执行于 SDK task 内，drain 不 cancel SDK task，自然跑到结束。

## Decisions

### 决策 1：删除 `CalcBotFallbackHandler`

直接删除类定义、`__init__.py` re-export、`main.py` import 与装配行、`tests/test_integration.py` 加法步骤。该 handler 无对应 spec，删除不影响任何能力契约。

- 备选：保留为"未路由文本的兜底回复"。被否：文件桥没有"对任意文本做有意义回复"的产品需求，保留只会让无意义文本得到一个加法错误结果，属于无需求的功能。

### 决策 2：task 链 + handler 自治取消

将排水从"drain 持有每个 task 的可取消状态并选择性 cancel"重构为"drain 只通知 + 等待，handler 自治可取消 task"。

**背景事实**：SDK 对每条消息创建一个 `background_task`（`asyncio.create_task`），在其中调用 `handler.process()`。asyncio 的取消是协作式的——`task.cancel()` 向 task 投递 `CancelledError`，在其下一个 `await` 点抛出，且抛出后无法从抛出点恢复执行。因此"下载可中断、归档不可中断"不能靠 catch CancelledError 后继续实现，必须靠**不 cancel 处于归档阶段的 task**。

**新架构**：

```
SDK background_task（每条消息一个，drain 追踪它来等结束）
    │
    ▼
MediaFileHandler.handle()
    │
    ├─ t1 = create_task(_download_phase())     ← 可中断，登记进 handler._interruptible_tasks
    ├─ await t1                                 ← t1 被 cancel → 这里抛 CancelledError
    │     ├─ 正常：拿到 download_result
    │     └─ 取消：reply "服务正在关闭，下载任务已取消"，return True
    │
    ├─ t1 从 _interruptible_tasks 移除（finally）
    │
    └─ _archive_phase() 内联执行               ← 不可中断，不在任何 set 里
       （保存 + 入库 + 回复）
```

**各组件职责**：

- `BaseMessageHandler` 新增 `cancel_tasks() -> None`（默认 no-op）。有可中断工作的 handler 覆盖此方法，cancel 自己登记的所有可中断 task。命名采用代码库统一的"task"术语；"只取消可中断部分、不可中断工作必须跑完"的语义由 docstring 与 handler 内部的 `_interruptible_tasks` 集合约定承载。
- `MediaFileHandler` 持有 `self._interruptible_tasks: set[asyncio.Task]`。下载阶段包成子 task 并登记；下载完成或被取消后从 set 移除；归档阶段内联执行不登记。`cancel_tasks` 遍历 set 调用 `task.cancel()`。下载器 `download_file_stream` 的 `except BaseException` 已保证取消时临时文件被清理，handler 无需额外擦屁股。
- `PipelineHandler` 内联排水状态（不单独抽 `TaskDrain` 类——task 链后排水仅剩约 30 行，抽类徒增委托层）：
  - `_draining: bool`、`_active_tasks: set[asyncio.Task]`（不再需要 Event）
  - `is_draining()` / `begin_drain()` / `register_current_task()` / `unregister_current_task()` / `drain_active_tasks(timeout)`
  - `begin_drain()`：置 `_draining=True`（关入口），并遍历所有 handler 调 `cancel_tasks()`（通知取消）
  - `drain_active_tasks(timeout)`：`asyncio.wait(_active_tasks, timeout=timeout)`，不再有选择性 cancel 循环
  - 删除 `mark_download_done`；`process()` 仍在入口检查 `is_draining()` 并注册/注销 SDK task。

**停机协作流程**：

```
BotService.stop()
  → pipeline.begin_drain()
      ├─ _draining = True          新消息 process() 直接 ACK
      └─ for h in handlers: h.cancel_tasks()
            └─ MediaFileHandler: for t in _interruptible_tasks: t.cancel()
  → pipeline.drain_active_tasks(10s)
      └─ await wait(_active_tasks)
            每个 SDK task 结局：
            ├─ 下载中：t1 被 cancel → handle 捕获 → reply 已取消 → SDK task 结束
            ├─ 归档中：t1 已移除，未被 cancel → 保存+入库+回复 → SDK task 结束
            └─ 命令中：rebuild 幂等，自然跑完 → SDK task 结束
```

**为什么比 Event 方案好**：

- **SRP**：排水不再持有"哪些 task 过了可中断点"的知识——这个知识属于 handler。排水只剩"关入口 + 通知 + 等待"的纯机制，与消息分发同属"消息处理流水线生命周期"这一职责，内联在 `PipelineHandler` 内不违反单一职责。
- **正交性**：handler 不再反向调用 `pipeline.mark_download_done()` 感知排水内部概念。耦合单向：排水 → handler（调 `cancel_tasks`），handler 不依赖排水内部机制。
- **意图导向**：`cancel_tasks` 业务无关，采用代码库统一的"task"术语且"interruptible"限定语义，任何 handler 实现它即可；`mark_download_done` 绑定"下载"语义，未来非下载 handler 调用会名不副实。
- **扩展性**：handler 可自由定义任意交替的可中断/不可中断阶段（下载→处理→API→保存），只需把可中断阶段包成子 task 登记进 set。排水永远零改动。

- 备选 A（保留 Event 机制）：被否。`mark_download_done` 时序契约脆弱，排水持有不属于它的阶段知识，且方法名无法扩展到非下载 handler。
- 备选 B（排水直接 cancel 所有 SDK task，handler catch CancelledError 区分阶段）：被否。asyncio 的 CancelledError 抛出后无法从抛出点恢复，归档阶段无法靠 catch 后继续实现；`asyncio.shield` 会产生脱离的后台 task，使排水的 wait 误判结束。
- 备选 C（将排水抽为独立 `TaskDrain` 类）：被否。task 链后排水仅剩约 30 行纯机制，抽类只增加委托层，不带来职责清晰度收益（排水与分发同属流水线生命周期），违反"拒绝过度设计"。

### 决策 3：删除 `add_handler`

该 fluent 方法仅在装配外无任何调用（`main.py` 通过构造函数 `handlers=[...]` 传入）。删除后，handler 列表只能在构造时指定，意图更清晰。

### 决策 4：`observability` spec 删除日志格式契约

将 `observability` 现有两个 Requirement（回调消息诊断日志、媒体下载链路诊断日志）全部标记为 REMOVED。日志输出降级为实现内部的排障手段，不再作为系统契约；不再为日志格式编写单元测试，运行效果由人工线上验收。

## Risks / Trade-offs

- [子 task 取消后临时文件残留] → 下载器 `download_file_stream` 的 `except BaseException` 已在取消时清理临时文件；handler 仅负责从 `_interruptible_tasks` set 中移除（finally 保证）。
- [阶段切换窗口期被取消] → 下载子 task 完成 → 从 set 移除 → 进入归档，这三步之间若 `cancel_tasks` 执行，子 task 已不在 set 中不会被 cancel，归档正常跑完——这是期望行为（归档不可中断），窗口期无害。
- [handler 的 set 是共享可变状态] → `add`/`discard` 在 asyncio 单线程事件循环中安全，无需锁；`cancel_tasks` 遍历 `list(self._interruptible_tasks)` 快照避免迭代时修改。
- [删除加法 handler 后，无路由文本消息会被静默 ACK] → 符合预期：文件桥不承诺对任意文本做回复；`CommandHandler` 仅匹配"重建索引"，其余文本正常 ACK 不回复。
- [observability spec 清空后日志格式无文档约束] → 日志仍由实现代码输出（`_log_received_message` 等），运维可通过 `LOG_LEVEL=DEBUG` 查看；缺失格式契约是有意为之，换取不写日志断言测试。

## Migration Plan

1. 无数据迁移、无新增依赖、无配置变更。
2. 按 tasks.md 顺序实施：删加法 → 改 BaseMessageHandler 接口 + MediaFileHandler task 链 → PipelineHandler 内联排水（通知+等待） → 删 add_handler → 改测试 → 改 observability spec。
3. 验证：`uv run pytest` 全量通过；`openspec validate cleanup-handler-pipeline --strict` 通过。
4. 回滚：整体作为单个提交，`git revert` 即可，无数据或配置残留。
