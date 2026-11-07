# Proposal

## Why

现有落盘策略为 `OUTPUT_DIR/yyyy-MM-dd/[发送者昵称]_时间戳.ext`。按日期建子目录使同一目录下的归档内容随时间无限分散，外部消费方（同步、备份、人工归档）需要递归遍历才能拿到全部文件；文件名中的发送者前缀使用昵称，既包含中文/特殊字符需要清洗，也不利于按人检索——应改用企业内唯一的 `senderStaffId`。

## What Changes

- 移除按日期创建的 `yyyy-MM-dd` 子目录，文件直接保存到 `OUTPUT_DIR` 根目录。
- 文件名格式由 `[发送者昵称]_时间戳.扩展名` 改为 `时间戳_senderStaffId.扩展名`，时间戳保留 `YYYYMMDD_HHMMSS_fff` 精度。`senderStaffId` 取消息原始字段 `senderStaffId`；该字段存在且清洗后非空时用 `时间戳_senderStaffId.ext`，缺失或清洗后为空时退回 `时间戳.ext`，不填充 `unknown` 之类的占位符。
- 时间戳语义保持不变：取每个文件落盘时的 `datetime.now()`，而非消息接收时间。同一 richText 多图逐张下载并落盘，各自得到不同的时间戳；`_1`、`_2` 自增后缀仅用于同一毫秒内的撞名兜底。
- 撞名时保留 `_1`、`_2` 自增后缀逻辑。
- **BREAKING**：`save_file()` 与 `generate_saved_filename()` 的 `sender` 实参改为 sender staff id；`sanitize_sender_name()` 重命名为 `sanitize_sender_id()` 并用于清洗该 id。
- 磁盘上已有的日期子目录文件保持原样，不做迁移；`metadata.sqlite` 中旧 `saved_path` 继续有效。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `file-storage`: “规范化目录结构与文件命名”要求改为直接落 `OUTPUT_DIR` 根目录，文件名为 `时间戳_senderStaffId.扩展名`，`senderStaffId` 缺失时降级为 `时间戳.扩展名`。
- `file-indexing`: 相关场景中“保存到本地日期目录”“重新写入当前日期目录”的表述改为根目录落盘，行为语义随之同步。

## Impact

- 代码：`app/utils/file_storage.py`（`save_file`、`generate_saved_filename`、`sanitize_sender_name` 重命名为 `sanitize_sender_id`）、`app/handlers/message.py`（调用点改传 `message.sender_staff_id`）、`tests/test_file_storage.py`。
- 数据：存量文件路径不变；新文件路径变为 `OUTPUT_DIR/<时间戳>_<senderStaffId>.ext`（`senderStaffId` 缺失时为 `OUTPUT_DIR/<时间戳>.ext`），`metadata.sqlite` 的 `saved_path` 字段自动记录新路径。
- 外部：依赖“按日期目录”组织归档的同步或备份脚本需改为读取根目录。
