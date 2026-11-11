# Spec Delta

## MODIFIED Requirements

### Requirement: 启动时向管理员发送索引快照报告
系统 SHALL 在服务启动完成索引一致性校验后，向配置的 `NOTIFY_STAFF_ID` 单聊目标发送当前索引总量快照报告。报告 SHALL 包含当前索引总量（用户数、文件总数、照片/视频/其他分项）与当前运行版本行。该快照 SHALL 并入机器人上线通知一并发送，与群聊上线通知共用同一标题，MUST NOT 作为独立消息额外发送，且 MUST NOT 包含面向群聊的用法介绍。当 `NOTIFY_STAFF_ID` 未配置时 SHALL 静默跳过。

#### Scenario: 配置管理员时启动发送快照
- **WHEN** 服务启动完成索引一致性校验且 `NOTIFY_STAFF_ID` 已配置
- **THEN** 系统向该管理员单聊发送当前索引总量快照报告

#### Scenario: 未配置管理员时启动静默
- **WHEN** 服务启动完成索引一致性校验但 `NOTIFY_STAFF_ID` 未配置
- **THEN** 系统跳过快照报告发送，继续后续启动流程

#### Scenario: 启动快照不发送到群聊
- **WHEN** 系统配置了群聊通知目标
- **THEN** 启动快照报告仅发送给 `NOTIFY_STAFF_ID` 指定的单聊目标，不向群聊发送

#### Scenario: 管理员快照附带版本行
- **WHEN** `NOTIFY_STAFF_ID` 已配置且当前运行版本为 `1.2.0`
- **THEN** 管理员收到的上线通知正文在索引快照之后附带 `当前版本：1.2.0`
