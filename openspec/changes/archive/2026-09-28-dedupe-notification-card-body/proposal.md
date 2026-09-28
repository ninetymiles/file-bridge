## Why

钉钉 markdown 卡片通过 `title=` 参数独立渲染卡片头（同时作为通知栏预览标题），而 `LifecycleNotifier` 的上线/离线通知正文首行又以 `###` 标题原样重复了同一段文字，导致单条卡片中标题出现两次。同时，单元测试对正文子串与标题全文做精确字符串匹配，把易变的展示文案耦合进测试，阻碍后续文案调整；契约层面只需验证"上线/离线时卡片确实发出"。

## What Changes

- 去掉上线/离线通知正文中与 title 重复的 `###` 标题行，正文只保留状态说明句；`title` 保持不变（卡片头与通知栏预览仍由它提供）。
- 上线正文改为 `服务已就绪，可以随时在群聊中@机器人 发送视频和照片，或直接私聊机器人发送视频照片。`（字面量"机器人"，SDK 无法获取机器人昵称，不做动态替换）。
- 离线正文改为 `服务已停止。`。
- 简化 `tests/test_lifecycle_notifier.py`：移除群聊上线用例与单聊离线用例中对正文内容（`"上线"`/`"离线"` 子串）及 `title` 全文的断言，只保留返回值与 `reply_markdown_card` 发送交互断言（上线、离线各验证有卡片发出）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无——纯展示层与测试清理。lifecycle-management 规范仅要求上下线时向已配置目标发送通知消息，不约束卡片正文排版与文案，无 spec 级行为变化；`.openspec.yaml` 已设置 `skip_specs: true`。）

## Impact

- 生产代码：`app/services/lifecycle_notifier.py` 中 `send_online_notification` / `send_offline_notification` 的 `content` 常量（各去掉一行标题前缀）。
- 测试：`tests/test_lifecycle_notifier.py` 两个用例删除文案断言，用例数量与覆盖的可观察行为不变；目标路由顺序、失败隔离、空卡片实例、超时等用例不受影响。
- 规范：无 delta；不改变发送目标、双目标独立发送、失败隔离、有界超时等既有契约。
- 依赖与对外 API：无变化。
