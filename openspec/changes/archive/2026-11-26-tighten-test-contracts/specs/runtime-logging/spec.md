# Spec Delta

## REMOVED Requirements

### Requirement: 启动版本与配置摘要

**Reason**: 启动摘要属于实现约束，不是对外可观测行为；将其写成规格会把「日志文本必须长期不变」固化为契约，导致测试只能断言日志字符串。

**Migration**: 无行为迁移；启动摘要保持不变，约束记录在变更 `design.md` 的「实现约定」中，由实现与评审保证，不再有自动化核验。

### Requirement: 接收消息正文在 INFO 级别可见

**Reason**: 接收摘要正文属于排障输出，其格式（`<imgN>` 占位符、@ 段剔除）已由 `richText` 合并与命令匹配的行为测试覆盖，不需要再以日志为判据重复核验。

**Migration**: 无行为迁移；日志保持现状，合并语义由 `message-pipeline` 的既有行为要求保证。

### Requirement: 媒体下载关键事件日志

**Reason**: 「每张媒体只产生一条下载开始日志」是日志层面的实现细节，无法替代下载行为本身的契约，重复约束会迫使测试断言日志条数。

**Migration**: 无行为迁移；改为在测试中断言下载接口的调用次数，日志保持现状。

### Requirement: 机器人回复内容在 INFO 级别可见

**Reason**: 回复是否送达由发送接口的返回值与用户可见回复保证；把「回复文本必须出现在 INFO」写成规格属于实现约束，并把日志顺序（发送先于记录）变成了测试判据。

**Migration**: 无行为迁移；回复日志保持现状，`design.md` 记录「发送先于本地日志」的实现约定。

### Requirement: 存储预热先于消息处理链所有 INFO 日志

**Reason**: 该要求的本质是「预热先于处理链」，已由 `storage-warmup` 能力覆盖；以「首条 INFO 日志」为载体使测试只能通过日志观察顺序。

**Migration**: 顺序行为迁移到 `storage-warmup` 的「预热先于处理链」表述；集成级用例继续验证「唤醒提示 → 探针完成 → 最终回复」的顺序。

### Requirement: 长连接生命周期结论日志

**Reason**: 连接结论行属于日志噪音治理的实现手段，不是用户或调用方依赖的行为；其文本与级别不应被测试锁死。

**Migration**: 无行为迁移；`design.md` 记录连接日志的呈现约定。

### Requirement: INFO 噪音与凭证信息边界

**Reason**: 日志级别边界（INFO 不出现 downloadCode/URL/令牌）是实现要求；凭证脱敏由新建的 `log-redaction` 能力记录，其余噪音治理不再作为可验证行为。

**Migration**: 凭证相关约束迁移至 `log-redaction`；httpx 逐请求日志抑制与 DEBUG 细节保留为实现约定，写入 `design.md`。
