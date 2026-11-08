# Spec Delta

## ADDED Requirements

### Requirement: 启动时索引快照通知
系统 SHALL 在服务启动完成索引一致性校验后、连接 SDK 之前，向配置的 `NOTIFY_STAFF_ID` 单聊目标发送当前索引总量快照报告。该通知 SHALL 仅发送给单聊管理员目标，MUST NOT 发送到群聊。当 `NOTIFY_STAFF_ID` 未配置时 SHALL 静默跳过，不阻断启动流程。

#### Scenario: 配置管理员时启动发送快照
- **WHEN** 服务启动完成索引一致性校验且 `NOTIFY_STAFF_ID` 已配置
- **THEN** 系统在连接 SDK 之前向该管理员单聊发送当前索引总量快照报告

#### Scenario: 未配置管理员时静默跳过
- **WHEN** 服务启动完成索引一致性校验但 `NOTIFY_STAFF_ID` 未配置
- **THEN** 系统跳过快照报告发送，继续连接 SDK

#### Scenario: 快照仅发送给管理员单聊
- **WHEN** 系统同时配置了群聊通知目标与管理员单聊目标
- **THEN** 启动快照报告仅发送给 `NOTIFY_STAFF_ID` 指定的单聊目标，不向群聊发送
