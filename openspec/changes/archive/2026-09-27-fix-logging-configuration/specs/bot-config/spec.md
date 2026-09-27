## ADDED Requirements

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
