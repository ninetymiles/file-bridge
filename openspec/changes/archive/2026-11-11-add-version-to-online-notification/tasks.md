# Tasks

## 1. 通知器版本行

- [x] 1.1 `LifecycleNotifier.__init__` 末尾新增 `app_version: str = "dev"` 并保存为实例属性；`uv run pytest tests/test_lifecycle_notifier.py` 全部通过（验证新增可选参数不破坏现有构造）
- [x] 1.2 `send_online_notification` 生成版本行 `当前版本：{app_version}`，群聊正文追加在用法介绍之后（空行分隔）；验证：新增用例断言群聊正文包含版本行
- [x] 1.3 staff 正文改为 `staff_snapshot + 版本行`；未提供快照时沿用群聊正文（含版本行）；验证：更新 `test_online_notification_staff_gets_snapshot_group_gets_usage` 为「以快照开头且包含版本行」，并新增两个目标都含同一版本行的用例

## 2. 入口装配

- [x] 2.1 `app/main.py` 构造 `LifecycleNotifier` 时传入 `app_version=get_app_version()`；验证：核对调用点，且 `uv run pytest -m general` 全部通过

## 3. 回归确认

- [x] 3.1 确认离线通知正文未变；验证：`tests/test_lifecycle_notifier.py` 中断言离线通知不含 `当前版本` 的用例通过
- [x] 3.2 运行全量 `uv run pytest -m general`；验证：退出码 0，无失败用例
