# Spec Delta

## MODIFIED Requirements

### Requirement: SQLite 元数据索引表管理
系统 SHALL 在 `OUTPUT_DIR/metadata.sqlite` 中维护唯一的元数据索引表，记录发送者、接收日期与时间、原始文件名、本地保存文件名、文件的 SHA-256 哈希值以及媒体类型。发送者信息 SHALL 分为两个独立列：`sender_id` 记录消息体的加密 `senderId`，`sender_staff_id` 记录消息体的 `senderStaffId`，两者 SHALL 与消息体原始字段名一一对应，取值互不替代、互不回退。`sender_id` 为 `NOT NULL`，仅在原始字段缺失时写入字面量 `unknown`；`sender_staff_id` 允许为空，原始字段缺失时保持 `NULL`，不写入 `unknown` 等占位符。媒体类型 SHALL 取消息的投递类型，取值为照片（`picture`）、视频（`video`）或文件（`file`）；`richText` 中的图片段 SHALL 记为照片。媒体类型列 SHALL 允许为空，以兼容旧版本服务写入的记录。

#### Scenario: 记录新文件元数据
- **WHEN** 新文件成功下载并保存到 `OUTPUT_DIR` 根目录
- **THEN** 系统在 SQLite 数据表中插入一条包含发送者、时间、原始名、本地名、SHA-256 与媒体类型的元数据记录

#### Scenario: sender_staff_id 存储原始完整值
- **WHEN** 系统保存一条携带 `senderStaffId` 的消息所对应的文件
- **THEN** `sender_staff_id` 列写入消息体该字段的原始完整值（例如生产环境为 16 位数字），不写入文件名所用的截断值，也不做任何重新格式化

#### Scenario: sender_id 仅存加密 senderId
- **WHEN** 消息同时携带 `senderId` 与 `senderStaffId`
- **THEN** `sender_id` 列写入 `senderId` 值；当 `senderId` 缺失时该列写入 `unknown`，MUST NOT 回退写入 `senderStaffId`

#### Scenario: senderStaffId 缺失时列保持为空
- **WHEN** 消息中不存在 `senderStaffId`，文件仍成功保存
- **THEN** `sender_staff_id` 列为 `NULL`，记录正常插入，不阻塞后续读取与统计

#### Scenario: richText 图片段记录为照片
- **WHEN** 系统保存 `richText` 消息中的一个图片段
- **THEN** 该记录的媒体类型为照片（`picture`）

#### Scenario: 媒体类型为空的记录
- **WHEN** 数据库中因旧版本服务写入或异常原因存在没有媒体类型的记录
- **THEN** 该记录的媒体类型列保持为空，不阻塞后续读取与插入

### Requirement: 数据库 schema 版本校验
系统 SHALL 以 SQLite 的 `PRAGMA user_version` 记录索引表结构版本，当前版本为 1。版本 1 的建表语句 SHALL 包含 `sender_id`、`sender_staff_id`、`sender_nick`、`created_at`、`original_filename`、`saved_path`、`sha256`、`file_size`、`media_type` 全部列。初始化数据库时，库文件不存在则 SHALL 创建当前结构并在同一事务内写入版本 1。

库文件已存在时，系统 SHALL 读取版本并仅接受等于当前版本的值。版本为 0（旧库、空文件或建库中断残留）、高于当前版本或其他不受支持的值时，SHALL 在启动阶段抛出显式错误并终止，MUST NOT 修改数据库或按其他结构继续运行。系统 SHALL NOT 自动升级旧结构；旧库由部署时人工删除后重建。未来结构变更 SHALL 从当前版本起依次递增并按顺序执行。

#### Scenario: 全新库直接建成当前版本
- **WHEN** 库文件不存在
- **THEN** 系统创建含 `sender_staff_id` 与媒体类型列的表，并在同一事务写入版本 1

#### Scenario: 缺少新列的同版本旧库要求人工删除
- **WHEN** 库文件版本为 1，但建表时不含 `sender_staff_id` 列（本次改动前创建的库）
- **THEN** 启动校验仅比对版本号，不会检测列缺失；部署时 SHALL 人工删除该库文件，由系统按当前 v1 结构重建，否则插入记录会因缺少该列报错

#### Scenario: 版本匹配时正常启动
- **WHEN** 库文件存在且版本等于当前版本
- **THEN** 系统不执行任何结构变更，直接进入后续启动流程

#### Scenario: 旧库或未初始化库拒绝启动
- **WHEN** 库文件存在但版本为 0
- **THEN** 系统抛出显式错误并终止启动，不对数据库做任何修改，错误信息提示删除库文件后重新启动

#### Scenario: 库版本高于代码版本时拒绝启动
- **WHEN** 库版本高于当前代码版本
- **THEN** 系统抛出显式错误并终止启动，不对数据库做任何修改

#### Scenario: 旧版本服务写入新结构库
- **WHEN** 不认识 `sender_staff_id` 与媒体类型列的旧版本服务连接版本 1 的库并插入记录
- **THEN** 插入成功，该记录的 `sender_staff_id` 与媒体类型为空，新版本统计时按扩展名回退归类
