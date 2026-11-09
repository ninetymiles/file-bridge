# Tasks

## 1. 数据库结构与写入

- [x] 1.1 `metadata_store.py` 在 v1 建表语句中加入 `sender_staff_id TEXT` 列（位置紧跟 `sender_id`），`CURRENT_SCHEMA_VERSION` 保持 1。验证：新建库的 `PRAGMA table_info(file_metadata)` 含该列
- [x] 1.2 `insert_record` 与 `async_insert_record` 在参数表末尾追加 `sender_staff_id: Optional[str] = None`，并写入 INSERT 语句与列清单。验证：既有位置参数调用不报错
- [x] 1.3 `message.py` 的 `sender_id` 取值改为 `message.sender_id or raw_data.get("senderId") or "unknown"`，去掉 `sender_staff_id` 兜底；`async_insert_record` 以关键字传入完整 `message.sender_staff_id`。验证：`senderId` 缺失时 `sender_id='unknown'` 且 `sender_staff_id` 保留原值

## 2. 文件名截断

- [x] 2.1 `file_storage.py` 的 `generate_saved_filename` 改为先清洗再取末 4 位，并去掉毫秒段：`time_str = ts.strftime("%Y%m%d_%H%M%S")`、`f"_{clean[-4:]}" if clean else ""`。验证：`manager4521` → `4521`，16 位数字 → 末 4 位，`abc` → `abc`，空值 → 无后缀，文件名形如 `20261109_155205_4521.png`
- [x] 2.2 确认截断值不外流：`save_file` 之外的调用方（回复 `atUserIds`、通知目标）仍使用原始完整 `senderStaffId`。验证：无代码将截断值回传给消息对象

## 3. 测试

- [x] 3.1 `tests/test_file_storage.py` 更新断言，并新增长 ID、短 ID、不足 4 位、空值四类用例，以及同秒撞名用例。验证：`uv run pytest tests/test_file_storage.py` 通过
- [x] 3.2 `tests/test_metadata_store.py` 新增 `sender_staff_id` 落库与空值用例；`tests/test_media_file_handler.py` 校验传给 `async_insert_record` 的 `sender_staff_id` 为完整值。验证：`uv run pytest tests/test_metadata_store.py tests/test_media_file_handler.py` 通过
- [x] 3.3 全量回归：`uv run pytest` 全量通过

## 4. 文档与部署

- [x] 4.1 `docs/storage.md` 更新表结构说明：新增 `sender_staff_id` 列、「`sender_id` 仅存加密 senderId、缺失写 unknown」、部署前删除旧库。验证：文档与建表语句一致
- [x] 4.2 `openspec validate sender-staff-id-handling` 通过
