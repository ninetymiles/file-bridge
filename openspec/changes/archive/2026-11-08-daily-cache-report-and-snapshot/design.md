# Design

## Context

服务基于 `asyncio` 事件循环运行，`BotService` 在 `start()` 中启动 SDK 后台协程。现有 `MetadataStore` 提供 `rebuild_index()`（清理失效记录）和 `get_index_statistics()`（聚合统计），`file_metadata.created_at` 以 `'%Y-%m-%d %H:%M:%S'` 字符串存储，字典序可比较。`LifecycleNotifier` 现有 `send_notification` 会向所有已配置目标（群+staff）广播。

## Goals / Non-Goals

**Goals:**
- 每天 09:00 自动检查缓存增量并通知管理员
- 启动时向管理员汇报当前索引总量
- 不引入第三方调度依赖，不改数据库 schema
- 手动报告与自动报告共用同一套总量模板

**Non-Goals:**
- 不做持久化的检查时间记录（内存基线即可）
- 不向群聊发送自动报告
- 不做补跑历史（服务重启后以启动时刻为新基线）

## Decisions

### 1. 调度：asyncio + 封顶 sleep

采用后台协程循环，每次计算到下一个 09:00 的秒数，与 3600 取最小值作为 sleep 时长。醒来后判断 `datetime.now() >= next_9am`，成立则执行检查。

**理由**：`asyncio.sleep` 使用单调时钟，系统时间修改不会导致永不唤醒；但机器休眠时单调时钟行为跨平台不一致（Linux `CLOCK_MONOTONIC` 不走，macOS 走）。封顶 1 小时确保休眠醒来后最多 1 小时内补跑。"达到或超过即触发"避免精确匹配在跳时后漏触发。

**替代方案**：`APScheduler` / `schedule` 库——对单一定时点过度设计，且违反项目"不引入非必要第三方依赖"约束。`threading.Timer` 递归——与 asyncio 事件循环集成不自然。

### 2. 时间基线：内存变量，不持久化

在调度器对象中维护 `last_check: datetime`，启动时初始化为 `now`，每次检查后更新。

**理由**：服务启动已执行 `rebuild_index` 同步磁盘状态，离线删除的文件会被清理。基线唯一用途是判断"距上次检查有无新增"，重启后以启动时刻为新基线即可满足需求，无需持久化。

### 3. 检查顺序：先清理后统计新增

每日检查执行顺序：`rebuild_index()` → 统计 `created_at > last_check` 的记录 → 更新 `last_check` → 有新增则发报告。

**理由**：先清理可排除"已缓存但文件后来被删"的记录，使增量统计只反映当前仍存在的新增缓存。

### 4. 按目标分流内容 + staff-only 发送

- `send_notification(title, content, staff_content=None)`：新增可选 `staff_content`，`_send_sync` 按目标类型选择内容；未传时所有目标收到相同内容。
- `send_to_staff(title, content)`：仅向 `notify_staff_id` 发送，供每日报告使用。
- 启动快照不单独发送，而是并入上线通知：`send_online_notification(staff_snapshot)` 使用同一标题 `🤖 File Bridge 机器人已上线`，群聊收到用法介绍，staff 收到索引快照。

**理由**：自动报告不应打扰群聊，故保留 staff-only 路径；而启动时若快照与上线通知分两条发送，staff 会连续收到两条冗余消息。合并后 staff 每次启动只收一条，群聊的用法介绍也得以保留。

### 5. 模板拆分：快照 + 增量

- `format_index_snapshot(stats) -> str`：输出 `当前索引总量：N 位用户上传 M 份文件 (照片 X，视频 Y，其他 Z)`，数字与前后中文之间以空格分隔，启动报告、每日报告总量行、手动指令共用。
- `format_daily_delta(delta_stats, last_check) -> str`：输出 `自YYYY-MM-DD HH:MM 新增：N 位用户上传 M 份文件 (照片 X，视频 Y，其他 Z)`，数字与前后中文之间以空格分隔。
- 每日完整报告 = `"📊 每日缓存统计：" + format_daily_delta(...) + "\n" + format_index_snapshot(...)`。

**理由**：快照模板复用避免三处格式漂移；增量模板独立承载"自上次检查"语义。`last_check` 格式化精确到分钟，足够清晰且简洁。

### 6. 手动报告去掉"最近新增"

修改 `format_index_report`（重命名为 `format_index_snapshot` 并精简），移除"最近新增"块与单日合并逻辑。

**理由**：增量信息由每日自动报告承担，手动报告回归"当前总量查询"的单一职责，减少手动/自动报告的信息重叠。

## Risks / Trade-offs

- **休眠后补跑可能与当天手动操作重叠** → 检查本身幂等（清理 + 统计），报告仅在有新增时发送，重复执行无副作用。
- **封顶 1 小时导致最多 1 小时延迟** → 对每日一次的低频通知可接受；如需更精确可减小封顶值，空转开销可忽略。
- **服务重启后基线重置，可能漏报重启前未发送的增量** → 启动快照报告会展示当前总量，管理员仍可感知整体状态；漏报的增量属可接受取舍，避免引入持久化复杂度。
- **`created_at` 无索引** → 每日一次的范围查询在当前数据量级下可接受；若未来数据量增长可再加索引，不在本次范围。

## Migration Plan

无数据库迁移、无配置变更。部署新版本后自动生效：启动上线通知随附索引快照，每日 09:00 执行增量检查。回滚即恢复旧行为（无自动报告，手动报告含最近新增）。
