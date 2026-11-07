# Tasks

## 1. 文件存储工具

- [x] 1.1 将 `sanitize_sender_name` 重命名为 `sanitize_sender_id`，缺失或清洗后为空时返回空串；同步更新 `tests/test_file_storage.py` 的对应用例，运行 `uv run pytest tests/test_file_storage.py` 通过
- [x] 1.2 修改 `generate_saved_filename`，按“清洗后的 id 是否为空”生成 `时间戳_senderStaffId.ext` 或 `时间戳.ext`，并更新测试断言覆盖两种格式，运行 `uv run pytest tests/test_file_storage.py` 通过
- [x] 1.3 修改 `save_file`，去掉日期子目录拼装，直接落 `OUTPUT_DIR` 根目录并保留撞名自增后缀；更新目录结构测试为断言根目录路径与 `_1` 后缀，运行 `uv run pytest tests/test_file_storage.py` 通过

## 2. 消息处理接线

- [x] 2.1 修改 `app/handlers/message.py` 的调用点，改传 `message.sender_staff_id` 并移除仅用于文件名的 `sender` 变量，确认 `sender_nick`/`sender_id` 仍照常写入元数据记录，运行 `uv run pytest -m general` 通过

## 3. 回归验证

- [x] 3.1 运行完整默认测试集 `uv run pytest`，确认无既有用例失败
- [x] 3.2 手动核对一次单聊图片落盘：确认文件出现在 `OUTPUT_DIR` 根目录且文件名形如 `YYYYMMDD_HHMMSS_fff_<senderStaffId>.png`，`metadata.sqlite` 的 `saved_path` 指向该文件

## Workflow follow-up

- 评审通过后归档变更。
- 归档后核对 `openspec/specs/file-storage/spec.md` 与 `openspec/specs/file-indexing/spec.md` 已同步为根目录落盘语义。
