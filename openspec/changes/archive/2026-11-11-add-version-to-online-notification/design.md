# Design

## Context

动机见 proposal.md。当前实现约束：

- 版本注入链路已存在：CI 从 git tag 取版本 → `Dockerfile` 的 `ARG/ENV APP_VERSION` → 运行时 `os.getenv`。[main.py](file:///Users/Liu/github/NinetyMiles/file-bridge/app/main.py#L70-L79) 的 `get_app_version()` 负责空值回退 `dev`。
- [main.py](file:///Users/Liu/github/NinetyMiles/file-bridge/app/main.py) 已 import `LifecycleNotifier`，通知器反向 import `get_app_version` 会形成循环依赖。
- `send_online_notification(staff_snapshot)` 对 staff 目标用 `staff_content` 替换正文，群聊目标用用法介绍；两个目标共用同一标题。
- 所有 `LifecycleNotifier(...)` 构造点均使用关键字参数，在参数列表末尾新增可选参数不破坏调用方；`app/core/runner.py` 只调用 `send_online_notification(staff_snapshot)`，签名无需变化。

## Goals / Non-Goals

**Goals:**

- 上线通知的群聊与单聊正文都出现当前运行版本，且两者一致。
- 版本来源单点：仍由 `get_app_version()` 决定，通知器不重复实现环境变量解析。
- 改动局限在通知器、入口装配与对应契约测试。

**Non-Goals:**

- 不修改版本注入链路（CI/Dockerfile）、不新增环境变量。
- 不改变离线通知与每日报告的正文。
- 不把版本放进消息标题。

## Decisions

### 决策 1：版本以构造参数注入通知器，而非在通知器内读环境变量

`LifecycleNotifier.__init__` 末尾新增 `app_version: str = "dev"`，`main.py` 传入 `get_app_version()`。

- 理由：`app/main.py` 已依赖 `LifecycleNotifier`，通知器反向 import 会造成循环依赖；同时让通知器保持无环境副作用，测试可直接构造任意版本。
- 备选：通知器内部 `os.getenv` — 代码更少，但重复 `dev` 回退逻辑、耦合环境、测试需 monkeypatch，放弃；由 `main.py` 组装两段正文再传入 — 文案散落两处、API 变宽，放弃。

### 决策 2：版本行统一在 `send_online_notification` 内拼接

正文末尾追加一段 `当前版本：{version}`，段落间用空行分隔，适配 markdown 卡片渲染：

- 群聊正文：`用法介绍 + "\n\n" + 版本行`
- staff 正文：`staff_snapshot + "\n\n" + 版本行`；未提供快照时沿用现有回退，staff 与群聊共用同一份带版本正文。

- 理由：两个目标的版本来源与格式在一处生成，避免群聊加了、单聊漏了；符合 proposal 中「两个目标一致」的要求。
- 备选：只改群聊文案 — 直接违背需求，排除。

### 决策 3：标题与离线通知保持不变

标题仍为 `🤖 File Bridge 机器人已上线`；`send_offline_notification` 不改。

- 理由：标题变长影响可读性与现有断言；用户明确只要求上线通知带版本。

## Risks / Trade-offs

- [现有测试 `test_online_notification_staff_gets_snapshot_group_gets_usage` 断言 staff 正文等于快照原文] → 改为断言「以快照开头且包含版本行」，契约仍然可验证。
- [版本未注入时显示 `dev`，可能被误读为异常] → 与启动日志的既有约定一致，属预期行为；发布镜像由 git tag 注入真实版本。
- [卡片正文多出一行，消息变长] → 仅一行短文本，无实际影响。

## Migration Plan

无数据迁移。发布即生效：tag 构建的镜像上线通知显示真实版本，本地或分支构建显示 `dev`。回滚只需回退代码，无状态残留。
