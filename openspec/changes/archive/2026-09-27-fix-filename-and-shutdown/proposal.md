## Why

归档 simplify-config-entry 时暴露两处存量缺陷。其一，commit 85e96bc（"Update stored file name"）把存储文件名时间戳改为带日期分隔符的格式，却漏改截断长度（`[:18]` 未随新增字符变为 `[:19]`），毫秒位从 3 位（`_123`）退化为 2 位（`_12`），测试也未同步，代码处于既非旧契约也非新格式的中间态。其二，`lib/runner.py` 的停机序列调用了 dingtalk-stream SDK（锁定版本 0.24.3）中并不存在的 `client.stop()`，并引用同样不存在的 `_stop_event`——两段死代码导致每次停机产生 AttributeError 警告，且对运行任务固定等待 5 秒（实际停机耗时约 5.1 秒），而取消（cancel）本已是唯一生效的停机机制。

## What Changes

- 修正存储文件名时间戳截断：`lib/file_storage.py` 中 `[:18]` 改为 `[:19]`，产出符合 85e96bc 意图的 `YYYYMMDD_HHMMSS_fff` 格式（3 位毫秒），同步更新注释。
- 更新 `tests/test_file_storage.py` 两个用例的期望值为新格式（`[Alice]_20260924_153045_123.pdf`、`[Bob]_20260924_153045_123.txt`）。
- 删除 `lib/runner.py` 停机序列中的死代码：`stop()` 内对 `client.stop()` 的调用（SDK 0.24.3 无此方法）、`request_stop()` 内对 `_stop_event` 的 getattr 段（SDK 无此属性）。
- 停机等待从 5 秒缩短为 1 秒：websocket 在 cancel 瞬间已关闭，SDK 会吞掉 CancelledError 并 `sleep(10)` 试图重连，等待该任务结束无意义；超时日志从 WARNING 降级为 INFO 并说明"任务被有意抛弃、进程退出阻止重连"。
- 更新 `lifecycle-management` 规范：停机机制描述由"调用 `client.stop()` 设置 SDK 停止标志"改为"取消运行任务 + 关闭 websocket + 有界等待"；`BotService.stop()` 的内部序列表述同步修订。`start()/stop()` 异步协议、信号拦截、二次中断强退、通知非阻塞等行为不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `lifecycle-management`：停机序列不再依赖 SDK 的 `stop()`/`_stop_event`（0.24.3 中不存在），改为取消运行任务并做有界（1 秒）等待；信号拦截范围、状态码 0 退出、二次中断强退、异步生命周期协议均保持不变。

## Impact

- **代码**：
  - `lib/file_storage.py`：1 处截断长度 + 注释（约 2 行）。
  - `lib/runner.py`：删除 `client.stop()` 调用段、`_stop_event` getattr 段；等待超时 5s → 1s；超时日志级别与文案调整（约 4 处局部改动，不新增函数/模块）。
  - `tests/test_file_storage.py`：2 个期望值字面量更新。
- **外部行为**：
  - 存储文件名格式随 85e96bc 的既定意图定型（日期与时间之间多一个 `_`，毫秒恢复 3 位）；碰撞计数兜底逻辑不变。
  - 停机耗时从约 5.1 秒降至约 0.1~1.1 秒；退出码仍为 0；离线通知 fire-and-forget 时序不变。
- **已知保留噪音**：SDK 自身在 CancelledError 时记录的 `[start] network exception, error=` 属 SDK 内部日志，本变更不修改第三方包，不消除该条日志。
- **依赖**：无新增/升级依赖，无 CLI 或环境变量变更。
