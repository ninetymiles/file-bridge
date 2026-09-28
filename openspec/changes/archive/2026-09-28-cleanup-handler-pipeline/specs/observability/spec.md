## REMOVED Requirements

### Requirement: 回调消息诊断日志
**Reason**: 日志输出不属于系统对外接口契约。以 SHALL/MUST 规定 INFO 摘要与 DEBUG 正文的精确字段，迫使测试断言诊断日志正文，违反 `AGENTS.local.md`"禁止将诊断日志作为功能测试的断言"。日志的具体格式与级别由实现与运维需要决定，运行效果由人工线上验收。
**Migration**: 删除该需求下全部 Scenario；不再为日志格式编写单元测试。若需排障，以 `LOG_LEVEL=DEBUG` 运行后人工查看日志。

### Requirement: 媒体下载链路诊断日志
**Reason**: 同"回调消息诊断日志"。换链与下载的日志细节属于排障辅助信息，非对外契约；强制规定 downloadCode/临时 URL/token 脱敏的输出形式会把日志断言引入测试。
**Migration**: 删除该需求下全部 Scenario；下载链路日志保留为实现内部的排障手段，不再受 spec 约束。
