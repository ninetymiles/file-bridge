# Design

## Context

参见 proposal.md — Why。当前落盘链路：`MediaFileHandler._process_one_image` 调用 `save_file()`，后者取 `datetime.now()`、拼日期子目录、生成 `[sender]_时间戳.ext` 文件名，再用 `shutil.move` 原子移交临时文件；撞名时在扩展名前追加 `_1`、`_2` 自增后缀。`metadata.sqlite` 的 `saved_path` 记录绝对路径，启动时的索引一致性校验只核验该路径是否存在，不感知目录结构。`OUTPUT_DIR` 在 `MetadataStore` 初始化时已创建，下载器也会创建 `OUTPUT_DIR/.tmp`。

## Goals / Non-Goals

**Goals:**
- 落盘目标统一为 `OUTPUT_DIR` 根目录，文件名携带 `senderStaffId` 时区分发送者。
- 保持原子移交与撞名不覆盖的既有保证。

**Non-Goals:**
- 不迁移磁盘上已有的日期子目录文件，也不改写 `metadata.sqlite` 中的历史 `saved_path`。
- 不改变 `metadata.sqlite` 中 `sender_id` 的取值逻辑（当前优先取加密的 `senderId`）。文件名用 `senderStaffId` 是独立取值，不触发现有元数据字段语义。
- 不引入目录轮转或分片策略去控制单目录文件数量。

## Decisions

**1. 命名逻辑留在 `generate_saved_filename`，`save_file` 只负责路径拼装。**
`sender` 参数语义改为 sender staff id，函数内部先清洗，再按“清洗结果是否为空”决定是否拼接 `_<id>`。备选：在 handler 里拼好前缀再传入——会把命名规则泄漏到调用方，否定。

**2. `sanitize_sender_name` 重命名为 `sanitize_sender_id`，缺失时返回空串而非 `unknown`。**
空串作为“不拼接前缀”的信号，避免占位符进入文件名。备选：返回 `Optional[str]` 由调用方判空——多一处分支，且清洗函数仍需处理异常字符，语义更绕。

**3. `senderStaffId` 取自 SDK 已解析的 `message.sender_staff_id`，不回退到 `raw_data` 查找。**
SDK 的 `ChatbotMessage.from_dict` 已经把原始 `senderStaffId` 映射到该属性，重复从 raw dict 取值属冗余。缺失即视为平台未提供，走降级命名。

**4. `save_file` 保留 `os.makedirs(output_dir, exist_ok=True)`。**
目标目录不再是“合并出多层路径”的副产物，显式确保根目录存在，同时让直接调用该函数的测试无需预建目录。备选：依赖调用方保证目录已存在——内部链路虽成立，但契约变得隐式。

**5. 撞名循环保持原样。**
时间戳精确到毫秒，`senderStaffId` 相同且同毫秒的并发落盘理论上可能发生，保留自增后缀即可，无需引入锁或唯一 ID。

## Risks / Trade-offs

- [单目录文件数量随时间无上限增长，NAS 列目录/备份遍历变慢] → 本变更的既定取舍，靠文件名时间戳保证排序与可检索；若后续成为瓶颈，再评估分片策略。
- [时间戳含义是“落盘时刻”而非“消息接收时刻”，richText 多图时间戳彼此不同] → 已在 spec 中显式定义场景，避免消费方误以为同一条消息的文件共享时间戳。
- [旧日期子目录与新根目录文件并存，归档目录不再结构统一] → 明确不迁移，索引校验按绝对路径工作，历史数据不受影响。
- [外部同步/备份脚本若硬编码日期目录层级会漏文件] → 部署时需同步调整读取根目录。

## Migration Plan

无需数据迁移。部署新版本后新收到的文件直接落 `OUTPUT_DIR` 根目录；回滚只需还原代码，已有文件仍可被索引校验与去重逻辑按 `saved_path` 正常识别。
