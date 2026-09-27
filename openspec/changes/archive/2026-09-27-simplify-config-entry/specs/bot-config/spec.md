## MODIFIED Requirements

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
