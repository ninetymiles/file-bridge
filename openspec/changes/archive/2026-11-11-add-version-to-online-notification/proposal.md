# Proposal

## Why

上线通知是部署后唯一主动推送到人手里的消息，但当前正文不含版本号。收到通知的人无法判断本次上线的到底是哪个版本，必须回到服务器查看启动日志（`File Bridge starting: version=x.y.z`）才能确认。版本注入与日志打印链路已经存在，只差把版本带进通知正文这一步。

## What Changes

- 上线通知正文未尾追加一行版本信息，格式为 `当前版本：x.y.z`（未注入时为 `dev`）。
- 群聊目标与 `NOTIFY_STAFF_ID` 单聊目标都带版本行：群聊为「用法介绍 + 版本行」，单聊为「索引快照 + 版本行」，仍共用同一标题、仍是一条消息。
- `LifecycleNotifier` 新增 `app_version` 构造参数（默认 `"dev"`），由入口传入 `get_app_version()` 的结果；通知器不直接读取环境变量，避免与 `app/main.py` 形成循环依赖。
- 离线通知保持不变，只保留原文案。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `lifecycle-management`: 「上线与离线主动通知」需求扩展为——上线通知正文 SHALL 包含当前运行版本，群聊与单聊目标一致；离线通知不受影响。
- `daily-report`: 「启动时向管理员发送索引快照报告」需求扩展为——并入上线通知的正文由「索引快照」变为「索引快照 + 当前版本行」。

## Impact

- 代码：`app/services/lifecycle_notifier.py`（新增参数与版本行拼接）、`app/main.py`（注入版本）、`tests/test_lifecycle_notifier.py`（契约断言）。
- 不受影响：`app/core/runner.py` 的 `send_online_notification` 调用签名、`Dockerfile` 与 CI 的版本注入链路（已存在）、离线通知、数据库结构、外部依赖。
- 配置：无新增环境变量或命令行参数。
