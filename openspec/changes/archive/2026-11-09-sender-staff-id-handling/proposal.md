# Proposal

## Why

文件名后缀当前使用完整的 `senderStaffId`，测试环境已产生形如 `20261109_095204_800_manager4521.png` 的较长文件名，生产环境的 16 位数字 ID 会使文件名进一步变长，而末尾 6 位已足够区分发送者。同时 `file_metadata` 表未保存 `senderStaffId`，只在 `sender_id` 列里以回退链混存 `senderId`/`senderStaffId`，导致列语义不纯、与消息体字段无法一一对应。

本次改动尚未部署，数据库可在正式部署时删除重建，因此无需迁移代码，直接按 schema 版本 v1 更新表结构。

## What Changes

- 文件名后缀从完整 `senderStaffId` 改为其清洗后的末 6 个字符；短 ID（如 `manager4521`）同样只取末 6 位（`er4521`）。
- `file_metadata` 表新增 `sender_staff_id TEXT` 列，直接存消息体原始 `senderStaffId`，与消息体字段名一一对应。
- `sender_id` 列的取值净化：仅取 `senderId`，缺失时写 `unknown`，不再回退到 `senderStaffId`。
- `PRAGMA user_version` 保持 1：新增列直接并入 v1 建表语句，不引入迁移链、不递增版本号。**BREAKING**：已存在的旧库（缺少新列）在启动时仍按既有逻辑被拒绝，需在部署时删除后重建。
- 统计口径不变：用户数去重仍基于 `sender_id`。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `file-storage`: 「规范化目录结构与文件命名」的文件名后缀规则由完整 `senderStaffId` 改为末 6 位。
- `file-indexing`: 「SQLite 元数据索引表管理」新增 `sender_staff_id` 列并明确 `sender_id` 净化取值；「数据库 schema 版本校验」补充 v1 建表内容包含新列的说明。
- `message-pipeline`: 发送者字段回退链 Scenario 更新为 `senderId -> unknown`，并记录回复 @ 提及依赖完整 `senderStaffId`、文件名截断值不得复用。

## Impact

- 代码：
  - `app/utils/file_storage.py`：命名函数取末 6 位。
  - `app/services/metadata_store.py`：建表语句加列、`insert_record` / `async_insert_record` 增加参数与列。
  - `app/handlers/message.py`：`sender_id` 取值净化，并传递 `sender_staff_id` 入库。
- 测试：`tests/test_file_storage.py` 文件名断言、元数据存储与插入相关测试同步更新。
- 数据：部署前删除旧 `metadata.sqlite`，由 v1 建表语句创建含 `sender_staff_id` 的新库。
- 不受影响：文件名截断值不参与回复 `atUserIds`（该处始终使用原始完整 `senderStaffId`）；`NOTIFY_STAFF_ID` 配置与生命周期通知逻辑不变；统计查询不变。
