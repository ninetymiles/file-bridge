## Why

当前生命周期通知（上线/离线）在同时配置 `NOTIFY_CONVERSATION_ID` 与 `NOTIFY_USER_ID` 时为二选一：实现中群聊目标优先，单聊目标被静默忽略，用户无法同时在群聊与个人单聊收到通知。此外，环境变量名 `NOTIFY_USER_ID` 与钉钉消息体中的加密字段 `senderId` 字面相近，容易误填为加密 ID（实测只有填写 `senderStaffId` 才能收到单聊通知），命名需要消除歧义。同时，SDK 在钉钉 OpenAPI 返回错误时会吞掉 HTTP 异常、仅记录日志并返回空卡片 ID，notifier 无法感知此类失败，会误报"发送成功"。

## What Changes

- 生命周期通知由"群聊/单聊二选一"改为"向所有已配置目标各自独立发送"：同时配置群聊与单聊目标时，两处都收到上线与离线通知。
- 单个目标发送失败（抛异常或 SDK 返回空卡片实例 ID）只记录 `WARNING` 日志，不阻断其余目标的发送；全部目标成功时整体结果才为成功。
- **BREAKING** 环境变量 `NOTIFY_USER_ID` 重命名为 `NOTIFY_STAFF_ID`，对应 CLI 参数 `--notify-user-id` 重命名为 `--notify-staff-id`，明确取值为钉钉消息 raw 结构中的 `senderStaffId`（企业内 userId）。不保留旧名称的兼容别名，沿用 `simplify-config-entry` 变更确立的 fail-fast 改名约定。
- notifier 以卡片实例返回的 `card_instance_id` 是否为空判定该目标发送失败，消除 SDK 静默失败导致的成功日志误报。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `bot-config`: "生命周期通知目标配置"需求修改——通知目标变量改名为 `NOTIFY_STAFF_ID` / `--notify-staff-id`；新增双目标同时配置时各自独立收到通知、单目标失败不阻断另一目标的行为约束。

## Impact

- 代码：`app/services/lifecycle_notifier.py`（发送逻辑与构造参数改名）、`app/main.py`（环境变量、CLI 参数与装配改名）。
- 测试：`tests/test_config.py`、`tests/test_lifecycle_notifier.py` 用例改名并新增双目标发送、单目标静默失败/异常隔离用例。
- 配置：本地 `.env` 中旧键 `NOTIFY_USER_ID` 需同步改名为 `NOTIFY_STAFF_ID`，否则启动后单聊通知配置失效；`.env.example` 未包含通知变量，无需改动。
- 无新增第三方依赖，仍使用 `dingtalk_stream` 0.24.3 的互动卡片投放接口。
