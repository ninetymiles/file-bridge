## ADDED Requirements

### Requirement: 生命周期通知目标配置
系统 SHALL 支持通过命令行参数或环境变量配置生命周期通知的接收目标，且命令行参数具有更高优先级。

#### Scenario: 仅通过环境变量配置通知目标
- **WHEN** 命令行未显式传入通知参数，但环境变量中设置了 `NOTIFY_CONVERSATION_ID` 或 `NOTIFY_USER_ID`
- **THEN** 系统解析并采用环境变量中定义的目标作为上线与离线通知的发送对象

#### Scenario: 命令行参数覆盖环境变量通知目标
- **WHEN** 环境变量中配置了通知目标，且命令行传入了对应的 `--notify-conversation-id` 或 `--notify-user-id`
- **THEN** 系统优先采用命令行参数指定的会话或用户作为通知目标

#### Scenario: 未配置通知目标
- **WHEN** 命令行与环境变量中均未提供通知目标
- **THEN** 系统正常启动，将通知目标标记为未配置并静默跳过通知逻辑
