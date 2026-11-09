# Spec Delta

## MODIFIED Requirements

### Requirement: 规范化目录结构与文件命名
系统 SHALL 将未重复的文件直接持久化保存在 `OUTPUT_DIR` 根目录，不创建按日期划分的子目录，并使用统一的文件命名格式 `时间戳.扩展名` 或 `时间戳_S.扩展名`，其中 `S` 为清洗后的 `senderStaffId` 末 4 个字符。取值顺序 SHALL 为先清洗（移除非法文件名字符与首尾空白）再截取末尾 4 个字符，避免截断后再清洗导致实际位数不足。`senderStaffId` 长度不超过 4 时 SHALL 原样使用全部字符。时间戳精度为秒（`YYYYMMDD_HHMMSS`），不含毫秒段。

#### Scenario: 目录与文件名生成
- **WHEN** 判定文件合法且非重复，需要落盘保存
- **THEN** 系统将文件直接保存到 `OUTPUT_DIR` 根目录，不创建 `yyyy-MM-dd` 之类的日期子目录，文件名为 `时间戳_末4位senderStaffId.原扩展名`，时间戳精度为秒（`YYYYMMDD_HHMMSS`）

#### Scenario: 长 senderStaffId 截取末 4 位
- **WHEN** 消息的 `senderStaffId` 为 16 位数字（生产环境取值形态）
- **THEN** 文件名后缀仅包含该值的末尾 4 个字符，例如 `20261109_095204_x456.png`，完整 ID 仍完整写入数据库 `sender_staff_id` 列

#### Scenario: 短 senderStaffId 同样截取末 4 位
- **WHEN** 消息的 `senderStaffId` 为 `manager4521`（测试环境取值形态，11 字符）
- **THEN** 文件名后缀为 `4521`，即该值末尾 4 个字符

#### Scenario: senderStaffId 长度不超过 4 位
- **WHEN** 消息的 `senderStaffId` 清洗后不足 4 个字符（例如 `abc`）
- **THEN** 文件名后缀为该值全部字符（`abc`），不补位、不截断为空

#### Scenario: senderStaffId 缺失时降级命名
- **WHEN** 消息的原始字段中不存在 `senderStaffId`，或该值清洗后为空
- **THEN** 文件名降级为 `时间戳.原扩展名`，不写入 `unknown` 等占位符

#### Scenario: 截断仅作用于文件名
- **WHEN** 系统生成文件名并入库
- **THEN** 截断后的 4 字符取值仅用于文件名；数据库 `sender_staff_id` 列、回复消息的 `atUserIds` 以及通知目标 SHALL 使用原始完整 `senderStaffId`，MUST NOT 复用截断值

#### Scenario: 同一毫秒内撞名
- **WHEN** 目标文件名在 `OUTPUT_DIR` 中已存在
- **THEN** 系统在扩展名前追加 `_1`、`_2` 等自增后缀保存，不覆盖已有文件

#### Scenario: richText 多图各自时间戳
- **WHEN** 单条 richText 消息包含多张图片
- **THEN** 每张图片按各自落盘时刻生成时间戳，文件名互不相同

## RENAMED Requirements

- FROM: `#### Scenario: 同一毫秒内撞名`
- TO: `#### Scenario: 同一秒内撞名`
