## MODIFIED Requirements

### Requirement: 生命周期通知目标配置
系统 SHALL 支持通过命令行参数或环境变量配置生命周期通知的接收目标，且命令行参数具有更高优先级。群聊目标通过 `NOTIFY_CONVERSATION_ID`（CLI：`--notify-conversation-id`，值为钉钉 `openConversationId`）配置；单聊目标通过 `NOTIFY_STAFF_ID`（CLI：`--notify-staff-id`，值为钉钉消息 raw 结构中的 `senderStaffId`，即发送者企业内 userId）配置。两类目标相互独立，可分别配置或同时配置；上线与离线通知 SHALL 发送给每一个已配置的目标。单个目标发送失败 SHALL NOT 影响其余目标的发送。

#### Scenario: 仅通过环境变量配置通知目标
- **WHEN** 命令行未显式传入通知参数，但环境变量中设置了 `NOTIFY_CONVERSATION_ID` 或 `NOTIFY_STAFF_ID`
- **THEN** 系统解析并采用环境变量中定义的目标作为上线与离线通知的发送对象

#### Scenario: 命令行参数覆盖环境变量通知目标
- **WHEN** 环境变量中配置了通知目标，且命令行传入了对应的 `--notify-conversation-id` 或 `--notify-staff-id`
- **THEN** 系统优先采用命令行参数指定的会话或用户作为通知目标

#### Scenario: 同时配置群聊与单聊目标
- **WHEN** `NOTIFY_CONVERSATION_ID` 与 `NOTIFY_STAFF_ID` 同时被配置（无论来自环境变量还是命令行参数）
- **THEN** 每次上线通知与离线通知都分别向群聊会话和单聊用户各发送一份，两处均收到通知

#### Scenario: 单个目标发送失败不阻断其余目标
- **WHEN** 通知发送过程中某一个目标抛出异常或被钉钉服务端拒绝（无有效卡片实例返回）
- **THEN** 系统继续向其余已配置目标发送通知，不因单个目标失败而中断整体通知流程，且本次通知的整体结果为失败

#### Scenario: 未配置通知目标
- **WHEN** 命令行与环境变量中均未提供通知目标
- **THEN** 系统正常启动，将通知目标标记为未配置并静默跳过通知逻辑
