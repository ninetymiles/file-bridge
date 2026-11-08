# Tasks

## 1. Metadata store: 增量统计查询

- [x] 1.1 在 `MetadataStore` 中新增 `count_new_since(last_check_str: str) -> IndexStatistics` 同步方法及 `async_count_new_since` 异步包装，查询 `created_at > last_check` 的记录并按用户数、文件数、照片/视频/其他分项聚合。验证：单元测试构造含不同 `created_at` 的记录，断言返回值正确区分增量与存量。

## 2. 报告模板调整

- [x] 2.1 将 `index_report.py` 中 `format_index_report` 重构为 `format_index_snapshot`，输出单行 `当前索引总量：N 位用户上传 M 份文件 (照片 X，视频 Y，其他 Z)`（数字与前后中文以空格分隔），移除"最近新增"块与单日合并逻辑。验证：更新 `test_index_report.py`，断言多日/单日/空索引均只输出总量单行。
- [x] 2.2 新增 `format_daily_delta(delta_stats: IndexStatistics, last_check: datetime) -> str`，输出 `自YYYY-MM-DD HH:MM 新增：N 位用户上传 M 份文件 (照片 X，视频 Y，其他 Z)`（数字与前后中文以空格分隔）。验证：单元测试断言格式与分项正确，`last_check` 精确到分钟。

## 3. LifecycleNotifier: staff-only 发送

- [x] 3.1 在 `LifecycleNotifier` 中新增 `async send_to_staff(title: str, content: str) -> bool`，仅使用 `notify_staff_id` 构造目标，复用 `_send_to_target`；未配置时返回 `True` 并静默跳过。验证：单元测试断言同时配置群与 staff 时仅调用 staff 发送，未配置 staff 时不调用 SDK。

## 4. 每日调度器

- [x] 4.1 实现 `DailyReportScheduler` 类，构造时注入 `metadata_store`、`notifier`、`logger`；维护内存 `last_check` 基线。实现 `async run_daily_check()`：先 `rebuild_index`，再 `count_new_since(last_check)`，更新 `last_check = now`，有新增且 staff 已配置时调用 `send_to_staff` 发送增量报告。验证：单元测试断言有新增时发送报告、无新增时不发送、未配置 staff 时不发送。
- [x] 4.2 实现 `async scheduler_loop()`：循环计算下一个 09:00，`sleep(min(差值, 3600))`，醒来判断 `now >= next_9am` 则执行 `run_daily_check`。验证：通过 mock `asyncio.sleep` 与时间，断言到达 09:00 时触发、未到达时不触发、休眠超时封顶生效。

## 5. 生命周期与启动集成

- [x] 5.1 在 `BotService` 中增加 `scheduler` 可选依赖；`start()` 中创建调度协程任务，`stop()` 中取消该任务。验证：更新 `test_runner.py`，断言启动时调度任务被创建、停止时被取消。
- [x] 5.2 在 `main.py` 启动流程中，索引一致性校验完成后、连接 SDK 之前，向 staff 发送启动快照报告（`format_index_snapshot` + `send_to_staff`），并初始化调度器基线。验证：更新 `test_integration.py` 或新增测试，断言启动时调用 `send_to_staff` 且报告为总量快照。

## 6. 集成验证

- [x] 6.1 运行 `uv run pytest`，确认所有单元测试通过且无回归。
- [x] 6.2 本地启动服务（配置 `NOTIFY_STAFF_ID`），验证：启动后收到快照报告；将系统时间或调度触发点调至 09:00 附近，验证收到增量报告（有新增时）或静默（无新增时）。
