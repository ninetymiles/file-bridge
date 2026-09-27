## Context

`LifecycleNotifier._send_sync` 目前用 if/else 二选一构造接收目标：`notify_conversation_id` 非空时走 `reply_specified_group_chat`，否则才走 `reply_specified_single_chat(notify_user_id)`，两个目标同时配置时单聊被静默丢弃。底层 `ChatbotHandler.reply_markdown_card(...)` 同步发起两次 OpenAPI 请求（创建卡片 + 投放卡片），其失败行为分两类：请求抛异常会向上传播；而 HTTP 错误被 SDK 捕获后仅记录日志并返回 `card_instance_id == ""` 的卡片实例（见 `dingtalk_stream` 0.24.3 `card_replier.py`），现有代码未检查返回值，误报发送成功。

命名方面，钉钉 raw 消息中的 `senderId` 是加密 ID，真正用于单聊投递的是 `senderStaffId`（企业内 userId，实测验证）。现有环境变量名 `NOTIFY_USER_ID` 与 `senderId` 字面相近，是误填的直接诱因。

## Goals / Non-Goals

**Goals:**
- 群聊与单聊目标同时配置时，上线/离线通知各自独立送达，单个目标失败不影响另一个。
- 通知结果真实反映投递状态：SDK 静默失败（空卡片实例 ID）可被 notifier 识别并记录。
- 通过命名消除"加密 senderId 与企业内 staffId"的混淆。

**Non-Goals:**
- 不改变通知的消息内容、卡片模板与发送时机（runner 中在线通知阻塞发送、离线通知 fire-and-forget 的既有编排不变）。
- 不支持多个群聊或多个单聊接收人，目标仍是"至多一个群 + 至多一个人"。
- 不为旧变量名/旧 CLI 参数提供兼容期或别名。
- 不改造 SDK 源码，失败检测仅基于其返回值。

## Decisions

### 1. 目标列表化，顺序独立发送

将配置的两个目标在 `_send_sync` 内组装为有序目标列表（先群聊、后单聊，仅包含已配置项），循环逐个构造 `ChatbotMessage` 并复用同一个 `ChatbotHandler` 发送。每个目标用独立的 try/except 包裹：异常或空卡片 ID 只记录包含目标类型的 `WARNING` 日志并标记该目标失败，循环继续。全部目标成功时 `_send_sync` 返回 `True`，否则返回 `False`。

- *替代方案：并发发送（线程池/asyncio.gather）*——两次 OpenAPI 调用并发度低、收益小，却会引入聚合异常与超时复杂度，拒绝。
- *替代方案：保留 if/else 仅补第二个分支*——失败隔离与结果聚合仍需重复逻辑，列表化后控制结构更简单。

### 2. 以返回的 card_instance_id 判空识别静默失败

`reply_markdown_card` 返回 `MarkdownCardInstance`，投放成功时 `card_instance_id` 为非空哈希串，SDK 内部任一步骤 HTTP 失败时为 `""`。发送后检查该属性：空串即视为本目标失败并记日志。该判空与异常捕获共同构成单目标的失败边界，不修改 SDK。

### 3. 改名 fail-fast，不留兼容别名

环境变量 `NOTIFY_USER_ID` → `NOTIFY_STAFF_ID`，CLI `--notify-user-id` → `--notify-staff-id`，argparse dest 与 `LifecycleNotifier` 构造参数同步改为 `notify_staff_id`；CLI help 文案注明取值为钉钉消息 raw 中的 `senderStaffId`。沿用 `simplify-config-entry` 变更确立的约定：旧 CLI 参数直接 unrecognized arguments 退出；旧环境变量不被读取（效果等同未配置单聊目标）。接受这种"显式断裂"以换取命名语义一次性收敛。

### 4. 超时语义保持不变

`send_notification` 仍由一次 `asyncio.wait_for(..., timeout=5.0)` 包裹整体 `_send_sync`，不为每个目标单独设置超时。双目标最坏耗时约为单次两倍，见风险项。

## Risks / Trade-offs

- **[Risk]** 双目标顺序发送使整体耗时翻倍，5 秒总超时在网络劣化时可能压缩甚至取消第二个目标的发送。
  → **Mitigation**：卡片接口正常为亚秒级，风险可控；若线上出现超时日志，再演进为按目标独立超时，本变更不预先复杂化。
- **[Risk]** 离线通知在 runner 中为 fire-and-forget，双目标使关闭阶段的发送窗口变大，极端情况下进程退出可能打断发送。
  → **Mitigation**：属既有生命周期编排行为，与既有 `graceful-task-drain` 议题相关，本变更不扩大处理；通知失败从不阻断退出的原则不变。
- **[Risk]** 改名后部署侧旧 `.env` / 启动脚本中的 `NOTIFY_USER_ID` 被静默忽略，单聊通知看似"突然失效"。
  → **Mitigation**：Migration Plan 明确改名检查项；help 文案与 spec 场景均标注新名称。

## Migration Plan

1. 将部署环境与本地 `.env` 中的 `NOTIFY_USER_ID=<staffId>` 改名为 `NOTIFY_STAFF_ID=<staffId>`，值保持为钉钉 `senderStaffId`（非加密 `senderId`）。
2. 启动脚本、systemd/Docker 启动命令中的 `--notify-user-id` 改为 `--notify-staff-id`。
3. 部署后同时配置两个目标，重启服务验证群聊与单聊各收到上线通知；停机验证各收到离线通知。
4. 回滚：还原本变更代码并将变量名/参数改回 `NOTIFY_USER_ID` / `--notify-user-id`，无数据迁移。
