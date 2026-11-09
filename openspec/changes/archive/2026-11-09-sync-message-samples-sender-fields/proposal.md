# Proposal

## Why

2026-11-09 线上实测日志（单聊 picture、单聊 text、群聊 text、群聊 richText 多图）显示，`senderNick`、`senderStaffId`、`senderId` 三个发送者字段在四类消息中均存在且同一用户跨会话取值一致；但现有 `message-pipeline` spec 的消息样本只登记了单聊 text 的发送者字段，其余样本缺失，且没有记录三个字段的取值形态与稳定性。spec 作为后续设计与实现的参考基准，需要补齐这部分实测事实。

## What Changes

- 在 `message-pipeline` 的「平台消息结构约定」中，为本次实测覆盖的样本补齐 `senderNick`、`senderStaffId`、`senderId` 字段：单聊 text、单聊 picture、群聊 text、群聊 richText。
- 新增 Scenario 记录四类消息的发送者字段一致性与跨会话稳定性：同一用户在同一环境内，单聊与群聊、text 与 richText/picture 的 `senderId` 取值相同。
- 新增 Scenario 记录三个字段的取值形态（脱敏）：`senderNick` 为中文昵称；`senderStaffId` 测试环境为 11 字符字母数字（如 `manager4521`），生产环境为 16 位数字；`senderId` 为 `$:LWCP_v1:$` 前缀的加密串，本次实测 43 字符，长度不写死。
- 将「群聊 richText 消息结构（@ 在段尾）」样本更新为本次实测的 5 段形态（2 个 picture 段 + 2 个换行 text 段 + 1 个尾部 @ text 段）。
- 明确 `<img1>`、`<img2>` 是系统合并时生成的占位符而非平台字段，避免后续把日志里的合并结果误读为原始负载。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `message-pipeline`: 「平台消息结构约定」补齐发送者字段样本，并新增发送者字段一致性与取值形态两个 Scenario。

## Impact

- 仅 spec 文档更新；实现与实测行为已一致，无需代码变更。
- 影响文档：`openspec/specs/message-pipeline/spec.md`。
- 不含 `senderStaffId` 文件名截断（末 6 位）的改动，该改动属于独立的 `file-storage` 变更。
