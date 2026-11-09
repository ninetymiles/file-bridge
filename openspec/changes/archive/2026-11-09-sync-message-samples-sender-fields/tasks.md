# Tasks

## 1. Spec 同步

- [x] 1.1 将 delta 的 `MODIFIED Requirements: 平台消息结构约定` 应用到 `openspec/specs/message-pipeline/spec.md`，补齐单聊 text、单聊 picture、群聊 text、群聊 richText 四类样本的 `senderNick`/`senderStaffId`/`senderId`，并新增「发送者字段在实测消息中均存在」「发送者字段取值形态与跨会话稳定性」两个 Scenario。验证：主 spec 中上述四类样本均含三个发送者字段，且两个新 Scenario 存在
- [x] 1.2 核对主 spec 与实测日志无矛盾（群聊 richText 段尾样本为 5 段 2 图；`<img1>`/`<img2>` 标注为系统占位符）。验证：`openspec validate sync-message-samples-sender-fields` 通过
- [x] 1.3 确认代码行为与更新后的 spec 一致，无需代码改动。验证：`uv run pytest` 全量通过

## Workflow follow-up

- 评审通过后归档变更，确认主 spec 保留全部修改。
