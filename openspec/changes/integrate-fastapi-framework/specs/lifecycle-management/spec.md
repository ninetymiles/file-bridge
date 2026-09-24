## ADDED Requirements

### Requirement: Lifespan 框架托管生命周期
系统 SHALL 支持通过 FastAPI 的 lifespan 上下文管理器编排后台 Stream 服务的启动与停机。

#### Scenario: Lifespan 驱动启动
- **WHEN** FastAPI 框架触发 lifespan 启动阶段
- **THEN** 系统在当前的事件循环中启动 Stream 客户端后台协程任务

#### Scenario: Lifespan 驱动停机
- **WHEN** FastAPI 框架触发 lifespan 停机阶段
- **THEN** 系统向预设会话发送离线通知、关闭底层长连接并取消后台协程任务
