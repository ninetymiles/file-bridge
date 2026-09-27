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
