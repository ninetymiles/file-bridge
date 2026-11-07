# Spec Delta

## MODIFIED Requirements

### Requirement: 规范化目录结构与文件命名
系统 SHALL 将未重复的文件直接持久化保存在 `OUTPUT_DIR` 根目录，不创建按日期划分的子目录，并使用统一的文件命名格式 `时间戳.扩展名` 或 `时间戳_senderStaffId.扩展名`。

#### Scenario: 目录与文件名生成
- **WHEN** 判定文件合法且非重复，需要落盘保存
- **THEN** 系统将文件直接保存到 `OUTPUT_DIR` 根目录，不创建 `yyyy-MM-dd` 之类的日期子目录，文件名为 `时间戳_senderStaffId.原扩展名`，时间戳精度为毫秒（`YYYYMMDD_HHMMSS_fff`）

#### Scenario: senderStaffId 缺失时降级命名
- **WHEN** 消息的原始字段中不存在 `senderStaffId`，或该值清洗后为空
- **THEN** 文件名降级为 `时间戳.原扩展名`，不写入 `unknown` 等占位符

#### Scenario: 同一毫秒内撞名
- **WHEN** 目标文件名在 `OUTPUT_DIR` 中已存在
- **THEN** 系统在扩展名前追加 `_1`、`_2` 等自增后缀保存，不覆盖已有文件

#### Scenario: richText 多图各自时间戳
- **WHEN** 单条 richText 消息包含多张图片
- **THEN** 每张图片按各自落盘时刻生成时间戳，文件名互不相同
