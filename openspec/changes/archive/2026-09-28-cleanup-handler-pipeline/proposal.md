## Why

当前 handler 流水线存在三处与项目定位和编码准则相悖的问题：其一，`CalcBotFallbackHandler` 是早期 calc bot 演示残留，与"文件桥"业务无关，徒增处理链长度与认知负载；其二，`PipelineHandler` 同时承担消息分发、接收日志、优雅关闭排水三项职责，且 `MediaFileHandler` 需反向调用 `pipeline.mark_download_done()` 并遵守"下载后、任意 await 前"的脆弱时序契约，属于漏抽象；其三，`observability` spec 以接口契约形式规定日志精确格式，迫使测试断言诊断日志正文，直接违反 `AGENTS.local.md`"禁止将诊断日志作为功能测试的断言"。

## What Changes

- **移除加法 handler**：删除 `CalcBotFallbackHandler` 类、`__init__.py` re-export、`main.py` 装配、集成测试中的加法步骤。
- **task 链 + handler 自治取消**：将排水从"drain 持有每个 task 的可取消状态并选择性 cancel"重构为"drain 只关入口、通知 handler 取消可中断 task、等待全部 SDK task 结束"。各 handler 自行管理可中断 task 的生命周期（`MediaFileHandler` 把下载包成子 task 登记进 set，归档内联执行不登记），通过 `BaseMessageHandler` 新增的 `cancel_tasks()` 接口响应取消通知。删除 `mark_download_done` 时序契约与 per-task Event 机制。排水状态内联在 `PipelineHandler` 内（不单独抽类）。
- **移除 `add_handler`**：该 fluent 方法从未在装配外使用，装配直接通过构造函数传入 handler 列表。
- **改写 observability spec**：移除"INFO 摘要必须包含/不得包含哪些字段""DEBUG 必须输出完整正文/下载码"等接口契约，降级为非契约的运维说明；对应 Scenario 一并删除。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `observability`: 删除日志格式相关的 Requirements 与 Scenarios（INFO 摘要字段约束、DEBUG 完整正文/下载码输出约束），日志输出不再作为系统契约，运行效果由人工线上验收。

## Impact

- **代码**：
  - `app/handlers/message.py`：删除 `CalcBotFallbackHandler` 与 `add_handler`；`BaseMessageHandler` 新增 `cancel_tasks()`；`MediaFileHandler` 改为 task 链（下载子 task + 内联归档）；`PipelineHandler` 内联排水（关入口+通知+等待），删除 `mark_download_done` 与 per-task Event。
  - `app/handlers/__init__.py`：移除 `CalcBotFallbackHandler` re-export。
  - `app/main.py`：移除 calc import 与装配行。
  - `app/core/runner.py`：停机调用面不变（仍调 `pipeline.begin_drain()`、`pipeline.drain_active_tasks()`）。
- **测试**：
  - `tests/test_integration.py`：移除加法测试步骤。
  - `tests/test_pipeline.py`：移除断言日志正文的 5 个用例。
  - `tests/test_drain.py`：按抽离后的排水对象接口调整，保留行为验证。
- **规范**：`openspec/specs/observability/spec.md` 改写。
- **依赖**：无新增第三方依赖；无 API/配置破坏性变更。
