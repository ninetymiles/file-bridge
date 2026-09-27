## 1. 配置改名

- [x] 1.1 修改 `app/main.py`：环境变量 `NOTIFY_USER_ID` → `NOTIFY_STAFF_ID`、CLI 参数 `--notify-user-id` → `--notify-staff-id`、argparse dest 改为 `notify_staff_id`，help 文案注明取值为钉钉 raw 消息中的 `senderStaffId`；同步更新 `LifecycleNotifier` 装配处的关键字参数；运行 `uv run pytest tests/test_config.py` 验证改名后配置用例通过
- [x] 1.2 更新本地 `.env`：将 `NOTIFY_USER_ID` 键改名为 `NOTIFY_STAFF_ID`（值不变）；确认 `.env.example` 无需改动

## 2. 通知器双目标与失败检测

- [x] 2.1 重构 `app/services/lifecycle_notifier.py`：构造参数 `notify_user_id` 改名为 `notify_staff_id`，`is_configured` 同步改名引用；将 `_send_sync` 的 if/else 改为按"群聊→单聊"顺序遍历已配置目标逐个发送，每个目标独立 try/except，失败仅记录含目标类型的 `WARNING`，全部成功才返回 `True`
- [x] 2.2 在单目标发送后检查返回的卡片实例：`reply_markdown_card(...)` 返回对象的 `card_instance_id` 为空串时判定该目标失败并记 `WARNING`（覆盖 SDK 吞掉 HTTP 错误的静默失败路径）；保持 `send_notification` 的 5 秒整体超时与未配置静默跳过行为不变

## 3. 测试

- [x] 3.1 更新 `tests/test_config.py`：通知目标的环境变量、CLI 参数与配置属性断言全部改为 `NOTIFY_STAFF_ID`/`--notify-staff-id`/`notify_staff_id`
- [x] 3.2 更新 `tests/test_lifecycle_notifier.py`：构造参数改名；新增双目标同时配置时 `reply_markdown_card` 被调用两次（群/单聊各一）的用例；新增单目标抛异常时另一目标仍被发送、整体返回 `False` 的用例；新增单目标返回空 `card_instance_id` 时判失败并记日志的用例；运行 `uv run pytest` 全量通过

## 4. 验证

- [x] 4.1 运行 `openspec validate dual-notify-targets-and-staff-id --strict` 确认工件合法
- [x] 4.2 手工验证：同时配置 `NOTIFY_CONVERSATION_ID` 与 `NOTIFY_STAFF_ID`（值取单聊消息 raw 中的 `senderStaffId`），启动服务确认群聊与单聊各收到上线通知；触发停机确认两处各收到离线通知；仅配置一个目标时确认另一处无多余报错
