# bot-config Specification

## Purpose

定义钉钉机器人的凭证解析与启动配置规则，支持基于环境变量（含 .env 文件）的默认配置和命令行参数的高优先级覆盖，保障多环境灵活运行。

## Requirements

### Requirement: 凭证解析与配置回退
应用启动时，系统 SHALL 按照“命令行参数 > 环境变量（含 .env）”的优先级解析 `client_id` 与 `client_secret` 凭证。命令行参数 SHALL 统一采用减号分隔命名（`--client-id`、`--client-secret`）。

#### Scenario: 仅通过环境变量提供凭证
- **WHEN** 命令行未传入 `--client-id` 和 `--client-secret`，但环境变量或 `.env` 中定义了 `CLIENT_ID` 与 `CLIENT_SECRET`
- **THEN** 应用成功启动并使用环境变量中的凭证建立连接

#### Scenario: 命令行参数覆盖环境变量
- **WHEN** 环境变量或 `.env` 中定义了 `CLIENT_ID` 与 `CLIENT_SECRET`，且命令行显式指定了 `--client-id` 或 `--client-secret`
- **THEN** 应用优先采用命令行传入的参数值覆盖对应凭证

#### Scenario: 两处均未提供必要凭证
- **WHEN** 命令行与环境变量中均未提供 `client_id` 或 `client_secret`
- **THEN** 命令行参数解析失败并提示错误退出，阻止应用以空凭证运行

### Requirement: 容器运行环境配置
容器镜像构建与运行配置 SHALL 确保 Python 模块正确定位及输出流无缓冲。

#### Scenario: 容器启动命令
- **WHEN** 容器根据 Dockerfile 默认命令启动
- **THEN** 执行 `python -m app.main` 成功运行应用入口，而非错误的 `:app` ASGI 语法

#### Scenario: 容器日志无缓冲输出
- **WHEN** 容器环境内产生标准输出或标准错误日志
- **THEN** 容器配置 `PYTHONUNBUFFERED=1` 确保日志立即刷出至容器日志系统

### Requirement: 文件输出目录配置
系统 SHALL 支持通过环境变量 `OUTPUT_DIR` 或命令行参数 `--output-dir` 配置接收文件的存储与索引根目录。

#### Scenario: 环境变量提供输出目录
- **WHEN** 环境变量中配置了 `OUTPUT_DIR=/path/to/files`
- **THEN** 系统使用该路径作为多媒体文件分目录归档及 `metadata.sqlite` 的根路径

#### Scenario: 命令行参数覆盖输出目录
- **WHEN** 命令行指定了 `--output-dir /custom/path`
- **THEN** 系统优先使用命令行参数指定的输出路径

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

### Requirement: 日志级别配置
系统 SHALL 支持通过环境变量 `LOG_LEVEL` 配置应用日志级别，取值为标准日志级别名称 `DEBUG`、`INFO`、`WARNING`、`ERROR`（大小写不敏感），未配置时 SHALL 缺省为 `INFO`。根日志记录器默认级别 SHALL 为 `INFO`，使第三方库的 DEBUG 日志在默认配置下不输出；应用日志记录器级别由 `LOG_LEVEL` 决定。

#### Scenario: 缺省日志级别
- **WHEN** 环境中未设置 `LOG_LEVEL` 启动应用
- **THEN** 应用以 `INFO` 级别运行，应用 DEBUG 诊断日志与第三方库 DEBUG 日志均不输出，INFO 及以上业务日志正常输出

#### Scenario: 通过环境变量开启调试日志
- **WHEN** 环境中设置 `LOG_LEVEL=DEBUG` 启动应用
- **THEN** 应用日志记录器以 DEBUG 级别运行，完整消息诊断日志生效，且第三方库日志仍按根日志记录器的默认级别过滤

#### Scenario: 非法日志级别回退
- **WHEN** `LOG_LEVEL` 被设置为无法识别的值
- **THEN** 系统回退使用 `INFO` 级别并输出一条配置告警，不因非法配置而启动失败
