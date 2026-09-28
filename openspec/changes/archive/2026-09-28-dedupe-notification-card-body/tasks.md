## 1. 通知正文去重

- [x] 1.1 修改 `app/services/lifecycle_notifier.py`：删除 `send_online_notification` 与 `send_offline_notification` 中 `content` 首行与 `title` 重复的 `###` 标题前缀；上线正文改为 `服务已就绪，可以随时在群聊中@机器人 发送视频和照片，或直接私聊机器人发送视频照片。`，离线正文改为 `服务已停止。`；两个 `title` 常量保持不变；验证：`grep -n '### ' app/services/lifecycle_notifier.py` 无匹配，肉眼确认卡片头标题仍由 `title=` 提供

## 2. 测试解耦与验证

- [x] 2.1 简化 `tests/test_lifecycle_notifier.py`：删除群聊上线用例中 `args, kwargs = ...` 解包及 `"上线" in args[0]`、`kwargs.get("title") == ...` 两处文案断言，删除单聊离线用例中对应的 `"离线"` 子串与 title 全文断言；两个用例只保留 `result is True` 与 `reply_markdown_card.assert_called_once()`（即上线、离线各验证有一张卡片发出）；其余用例（双目标路由顺序、失败隔离、空卡片实例、超时）不动；验证：`uv run pytest tests/test_lifecycle_notifier.py -q` 全部通过
- [x] 2.2 运行 `uv run pytest -q` 全量测试通过，确认未影响其它测试；运行 `openspec validate dedupe-notification-card-body --strict` 确认工件合法
- [x] 2.3 真实钉钉环境人工确认：上线/离线卡片的卡片头标题与正文不再重复展示（正文文案后续由维护者自行调整，不要求与当前措辞一致）
