# Design

## Context

动机见 [proposal.md](proposal.md) - "Why"。本设计只处理测试写法与构造注入点，不改变任何对外行为。

上一轮 `tighten-test-contracts` 已确定两条前提：

- 日志不作为测试判据；
- 叶子接口必须保留独立用例，失败要能沿着「叶子 → 支路 → 主干」定位。

本设计在同一原则下处理「断言落在被测对象内部」的问题。

## 白盒判据

一个用例算白盒，当且仅当满足任意一条：

1. 断言或调用落在被测对象自己的内部符号上（`_` 前缀函数、私有属性、模块内导入的协作者）。
2. 用补丁替换被测对象自己的内部协作者，而不是外部系统边界（HTTP、SDK、时钟、事件循环）。
3. 断言「实现怎么做的」：内部调用顺序、内部休眠切块、对象身份、内部任务集合。

替换外部边界（钉钉 SDK、HTTP transport、时钟、休眠）属于合法接缝，不在本变更范围。

## Goals / Non-Goals

**Goals:**

- 测试只通过公开构造参数与公开方法观察行为。
- 生产侧补三个小接缝，消除反射与私有注入。
- 删除重复或零信息量的断言，同时不降低叶子覆盖。

**Non-Goals:**

- 不新增业务行为，不改规格（`skip_specs: true`）。
- 不给 `LifecycleNotifier` 增加发送协作者抽象。
- 不改 `test_drain`、`test_photo_review` 的 HTTP 注入、`FakeClock` / `FakeSleep` 等合理接缝。
- 不合并 `decouple-callback-ack` 的改动。

## Decisions

### D1：删除零信息量断言

| 用例 | 为什么删 |
|---|---|
| `test_index_report.test_snapshot_does_not_access_database` | 全局替换 `sqlite3.connect` 属负向实现断言；渲染器只接收 `IndexStatistics`，类型已保证不碰库 |
| `test_command_matching` 的 `passage_inputs` / `query_inputs` | 锁死「先嵌入目录、再嵌入查询」的内部协议；`match()` 返回值才是契约 |
| `test_runner` 的 `logger.warning.called` | 等价于日志断言；启动继续执行已由 `started` 事件证明 |
| `test_runner` 的三处 `client.stop.assert_not_awaited()` | 这是「SDK 没有 stop API」的实现约束，不是可观察行为；连接关闭由后续断言覆盖 |
| `test_daily_report_scheduler` 的 `sleeper.calls == [3600]` | 规格只要求「单次等待时长有上限」，具体切块是内部策略 |
| `test_daily_report_scheduler` 的 `asyncio.all_tasks()` 差集 | 反查事件循环内部任务，脆弱且不可读；调度效果由报告发送断言覆盖 |
| `test_lifecycle_notifier` 的 `is group_message` 与「第一条是群」 | 规格未规定群/单聊发送顺序；身份断言锁死 SDK 返回值传递路径 |

备选方案：保留但加注释「实现细节」→ 否决，注释无法阻止后续重构踩碎。

### D2：媒体处理器改用真实存储与真实元数据

现状问题：

- `assert mock_store.async_insert_record.call_args[1]["media_type"] == "picture"` 断言的是内部 kwarg 传递，不是入库结果。
- `patch("app.handlers.message.extract_media_metadata")` 替换模块内协作者，断言的是桩返回值。

改法：

1. 用 `MetadataStore(output_dir=tmp_path)` 构造处理器，落盘后直接 `get_connection()` 读回记录，断言 `media_type`、`sender_id`、`sender_staff_id`、`saved_path`、`original_filename`、`file_size`。
2. 媒体元数据行用例改用真实图片：复用 `tests/fixtures` 下已有 EXIF 样本；无合适样本时用 PIL 生成最小 EXIF JPEG。断言回复第二行符合 `media-metadata` 定义的格式要素（时间 / 光圈 / 快门 / ISO 至少出现其一），不断言字符串拼接细节。
3. 下载器继续用 `MagicMock` —— HTTP 是外部边界。

备选方案：保留 mock 但断言完整 kwargs → 否决，等于把入库实现抄进测试。

### D3：引导回复改在处理器层验证

现状：直接调用 `build_guide_reply`，并 `monkeypatch.setattr("app.handlers.message.random.choice", ...)`。

改法：构造 `CommandHandler(matcher=假匹配器(返回 None), dispatch_table={})`，调用 `handle()`，断言返回意图：

- 层级为 `SECONDARY`；
- 含 4 个能力项（`"• "` 计数为 4）；
- 有文本输入时存在共情前缀、无文本时回复以模板内容开头；
- 结尾是提问式引导（可从常量集合断言，但不断言具体某一句）。

不再 patch `random.choice`；随机性由「集合成员关系 + 结构计数」吸收。

### D4：通知器按内容定位调用

现状：`calls[0]` / `calls[1]` 顺序推断目标，且 `is` 比较 SDK 对象身份。

改法：从 `reply_markdown_card` 的调用参数中找 `body.startswith(snapshot)` 的那一条断言快照内容，找包含「服务已就绪」的那一条断言用法说明；两条都必须带同一标题与版本文本。删除顺序断言与身份断言。

### D5：`create_pipeline` 接受可选 `file_downloader`

```python
def create_pipeline(
    output_dir, metadata_store, dingtalk_client, matcher,
    logger=None, reviewer=None, wake_warmup=None, file_downloader=None,
) -> PipelineHandler:
    if file_downloader is None:
        file_downloader = FileDownloader(
            output_dir=output_dir, dingtalk_client=dingtalk_client, logger=logger
        )
```

理由：集成测试需要注入 `httpx.MockTransport`，目前只能 `handler.file_downloader._http_client = ...` 反射写入。`FileDownloader` 构造已支持 `http_client`，把选择权上移到装配层即可，不新增抽象。

备选方案：给 `create_pipeline` 传 `http_client` → 否决，装配层不该知道下载器内部用了什么 HTTP 客户端。

### D6：`PipelineHandler` 接受 `warmup_delay`

```python
def __init__(..., storage_probe=None, wake_warmup=None, warmup_delay: float = 3.0):
    self.warmup_delay = warmup_delay
```

`_dispatch` 调用 `ensure_storage_ready(..., delay=self.warmup_delay)`。

理由：测试需要把 3 秒压缩到毫秒级，目前只能 patch 模块内导入的 `ensure_storage_ready`（耦合导入位置）。该值是构造参数，不是运行时配置，不违反 `storage-warmup` 中「3 秒阈值固化、不新增运行时配置项」——生产装配不传，保持 3.0。

备选方案：patch 保留 → 否决，测试会因 `_dispatch` 改变导入方式而碎。

### D7：`ReviewGate` / `build_wake_warmup` 公开化

把 `app/main.py` 中的 `_ReviewGate` 与 `_build_wake_warmup` 改名为 `ReviewGate` 与 `build_wake_warmup`，行为不变，测试导入公开名。

理由：这两个对象是被 `main()` 装配的独立构件，语义上属于公开装配 API；仅因下划线被当作私有，才逼出「测私有函数」的用例。

备选方案：删除该用例 → 否决，会丢失「探测失败时不得预热」这条真实契约的叶子覆盖。

### D8：不给 `LifecycleNotifier` 增加发送协作者

现状 patch `dingtalk_stream.ChatbotHandler` 属于 SDK 边界替换，保留。仅按 D4 收敛断言。

备选方案：引入 `card_sender` 接口 → 否决，当前只有一种发送实现，抽象只为测试服务，违反「拒绝过度设计」。

### D9：明确不动的部分

- `test_drain` 的 handler 替身：验证的是 `PipelineHandler` 的公开 drain 行为，替身实现的是 `BaseMessageHandler` 接口。
- `test_photo_review` 的 `_Recorder`：`http_client` 是生产构造函数参数，属外部边界注入。
- `FakeClock` / `FakeSleep`：`clock` / `sleep` 是 `DailyReportScheduler` 的公开构造参数。
- `SemanticCommandMatcher(embedder, catalog=...)`：embedder 是构造注入，类边界黑盒。

## 逐文件改法

| 文件 | 动作 |
|---|---|
| `app/main.py` | `create_pipeline` 增加 `file_downloader` 参数；`_ReviewGate`→`ReviewGate`；`_build_wake_warmup`→`build_wake_warmup`；`main()` 内引用同步 |
| `app/handlers/message.py` | `PipelineHandler.__init__` 增加 `warmup_delay=3.0`；`_dispatch` 传给 `ensure_storage_ready` |
| `tests/test_integration.py` | 构造 `FileDownloader(http_client=...)` 传入 `create_pipeline`；删除 `hasattr` 查找与 `_http_client` 赋值；`ensure_storage_ready` 的 monkeypatch 改为 `warmup_delay`；`metadata_store` 直接复用变量；`ReviewGate` / `build_wake_warmup` 用公开名 |
| `tests/test_media_file_handler.py` | 入库断言改真实 `MetadataStore`；元数据行改真实图片；保留下载器 mock 与「处理器不得自行回复」断言 |
| `tests/test_command_handler.py` | 两条 `build_guide_reply` 用例改为 `handle()` 层断言；删除 `random.choice` patch |
| `tests/test_lifecycle_notifier.py` | 删除身份断言与顺序假设；改为按内容定位调用 |
| `tests/test_daily_report_scheduler.py` | 删除 `sleeper.calls` 与 `all_tasks()` 反查；保留报告内容、跳过发送、幂等启停断言 |
| `tests/test_runner.py` | 删除 `logger.warning.called` 与三处 `client.stop` 负向断言；保留幂等、顺序、快照传递断言 |
| `tests/test_command_matching.py` | 删除 `passage_inputs` / `query_inputs` 断言；保留 `match()` 结果、阈值、缓存目录、构造失败用例 |
| `tests/test_index_report.py` | 删除 `test_snapshot_does_not_access_database` |

## Risks / Trade-offs

- [改成真实 `MetadataStore` 后单测变慢] → 仅 tmp 目录写一个 SQLite 文件，毫秒级；换来的是真正的入库契约。
- [真实 EXIF 样本依赖 fixture 文件] → `tests/fixtures` 已有样本；缺样本时用 PIL 生成，避免新增二进制文件。
- [引导回复改为结构断言后，无法锁死具体措辞] → 措辞本就是随机设计，结构断言才是真契约。
- [`warmup_delay` 构造参数被误用于生产] → 默认值 3.0，`main.create_pipeline` 不传；代码评审可拦截。
- [删除顺序断言后，若真出现「单聊先于群聊」的回归] → 规格未规定顺序，该变化不构成回归。

## Migration Plan

- 先落三处生产接缝（纯签名与重命名），再改测试，确保每一步都能单独跑通。
- 回滚：还原提交即可；无数据、配置残留。
- 验证：`uv run pytest` 全绿；全仓库检索无 `_http_client`、无 `patch("app.handlers.message.extract_media_metadata")`、无 `_ReviewGate`。

## Open Questions

无。
