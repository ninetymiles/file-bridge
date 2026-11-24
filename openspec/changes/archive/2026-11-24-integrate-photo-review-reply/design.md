# Design

## Context

- `MediaFileHandler`（`app/handlers/message.py`）负责单条 `picture`/`video`/`file` 与群聊 `richText` 图片段：`_process_one_image` 完成下载、去重、落盘、入库和 EXIF 提取，返回 `_ImageProcessResult`；`_handle_media`（单图）与 `_handle_rich_text`（多图）各自把它拼成 `ReplyIntent`。
- `PipelineHandler._dispatch` 收集所有 handler 的 intent，按最高 tier 合并成一条消息，调用 `async_reply_text` 发送后才返回 ACK。`async_reply_text` 内部用 `asyncio.to_thread(self.reply_text, ...)`，已经承担"额外发一条消息"的能力（存储唤醒提示就走的这条路），不需要新的发送通道。
- `PipelineHandler.drain_active_tasks(timeout=10.0)` 只等待 `_active_tasks` 中的 SDK 消息任务；ACK 之后创建的 task 不在其中，停机时会被放弃。
- `ensure_storage_ready`（`app/services/disk_warmup.py`）提供"异步探测 + 定时器赛跑"的现成范式：定时器只决定要不要给用户交代，不取消被等待的工作。本变更复用它的赛跑结构，但把"无上限等待"换成有上限的批量截止。
- `PhotoReviewer.review()` 已是异步、永不抛错、失败返回 `None`；图片解码是同步 Pillow 调用。`ReviewConfig.from_env()` 目前三项必需、缺失抛错。
- `BotService.start()`（`app/core/runner.py`）是启动期的异步入口，先于 `client.start()`；`app/main.py` 的 `main()` 是同步装配点。
- 实测（本地 ollama + gemma4:e4b-mlx）：热调用约 1.9 秒；模型已卸载时冷加载约 8.94 秒；`GET /models/{model}` 返回 200 不会把模型加载进显存；模型名中的 `:` 必须 URL 编码，编码后返回 200，不存在的模型返回 404；`httpx.Timeout` 是逐操作超时，不是总墙钟上限。

## Goals / Non-Goals

**Goals:**

- 让点评成为回复的可选附加内容：启用时出现在 EXIF 之后；任何失败、超时、未配置都退回今天的回复。
- 把"等待点评"限制在 15 秒的合并窗口内，窗口外改为第二条消息，避免拖慢首次回复与 ACK。
- 用一个跨图片共享的 60 秒总时限收口后台任务与连接，保证"最晚一分钟内要么有评点、要么永远没有"。
- 保持测试完全离线：不连真实网关、不读写进程环境变量、不依赖真实延时。

**Non-Goals:**

- 不改变 CLI 的配置、输出与无总超时语义。
- 不做点评缓存、异步队列、跨消息去重或点评入库。
- 不在启动时预热模型（探测只验证地址与模型名）。
- 不为点评任务增加停机 drain 等待；丢弃未完成的点评是可接受结果。
- 不在本次引入 FastAPI 或改变运行形态。

## Decisions

### D1. 接入点在 `MediaFileHandler`，不在 `_dispatch`，也不在 FastAPI

点评需要"已落盘的文件路径"和"这条消息是否含图片"，只有 `MediaFileHandler` 同时知道两者。`_dispatch` 是通用回复合并器，不应理解照片语义；FastAPI 只是未来的运行外壳，链路上的行为一致。

被否掉的方案：在 `_dispatch` 里根据 intent 类型判断后统一附加点评——它拿不到保存路径，也拿不到 `msgtype`，只能靠回读元数据表反查，复杂度更高。

### D2. 点评任务与首次回复解耦：`_ImageProcessResult.saved_path` + `_ReviewBatch`

`_process_one_image` 只多返回一个 `saved_path`（保存成功时非空），**不**在里面等待点评。图片保存完成后，handler 才开始点评任务，从而保证：

- 落盘、入库、EXIF 提取的耗时与今天一致；
- 多图时可以并发点评，且共享一个窗口；
- 15 秒窗口从"首次回复就绪"开始计时，而不是从下载开始。

新增内部助手 `_ReviewBatch`（`message.py` 内私有）：

```
class _ReviewBatch:
    def __init__(reviewer, entries: list[tuple[int, str]], logger)
    def start()                                  # 每张照片一个 create_task
    async def wait(timeout) -> (dict[int, str], list[Task])   # 不取消超时项
    async def finish(cutoff) -> dict[int, str]   # 补发阶段：等待剩余，到点取消
```

`wait()` 用 `asyncio.wait(tasks, timeout=...)` 而不是 `asyncio.wait_for(gather(...))`：后者在超时时会取消整批，连已经完成的结果一起丢掉；前者能把"已完成"与"仍挂起"分开处理。返回值只包含非空点评，失败与 `None` 一律不进入结果。

空批次（没有保存成功的照片）直接跳过，不创建 `asyncio.Task`，也避免 `asyncio.wait([])` 抛 `ValueError`。

### D3. 两段式消息通过 `ReplyIntent.after_reply` 保证顺序

新增 `ReplyIntent.after_reply: Optional[Callable[[], None]] = None`，由 `_dispatch` 在首次回复发送成功之后同步调用。handler 在返回 intent 前就创建好补发任务，任务先等待一个 `asyncio.Event`；`after_reply` 只负责 `set()` 这个门闩。这样首次回复仍然走既有的"收集 intent → 合并 → 发送"路径（不会和命令回复拆成两条），第二条消息一定晚于第一条，任务从创建起就在 `_review_tasks` 里，停机取消不会漏掉。

被否掉的方案：

- **handler 自己发第一条并返回 `None`**：私聊会触发 `_dispatch` 的"不支持类型"兜底回复，且与命令回复的合并语义被破坏。
- **handler 自己发第一条并返回空文本 intent**：需要给 `_dispatch` 增加"跳过空文本"的隐式规则，含义不清晰。
- **在 `PipelineHandler` 上维护 per-message 的 follow-up 列表**：`_dispatch` 本身并发执行，跨消息共享列表需要额外的作用域管理。挂在 intent 上天然随消息走。
- **`after_reply` 自己 `create_task`**：任务在首次回复发送后才存在，停机若恰好发生在创建前，取消集合里没有它；门闩方案没有这个空窗。

`after_reply` 里要用的发送函数就是 `pipeline.async_reply_text`，签名与唤醒提示一致。

### D4. 15 秒合并窗口与 60 秒总时限是两个独立的数

```
t=0        首次回复就绪（文件名 + EXIF），点评任务已启动
t=0..15    合并窗口：与 asyncio.wait(tasks, timeout=15) 赛跑
             全部完成 -> 点评并入首次回复（无前缀），1 条消息
             窗口到期 -> 首次回复不带点评（1 条），after_reply 接管
t=15..60   补发阶段：等待剩余任务，到点取消并 WARNING
             有成功结果 -> 第二条「照片点评：…」
             全部失败   -> 不发第二条
```

- **窗口 15 秒**只回答"点评要不要并进第一条"，到期**不取消**请求。
- **总时限 60 秒**从这批点评启动时算起，是"第二条消息是否还存在"和"后台任务是否回收"的截止线。
- 建连超时单独 5 秒，用来快速识别"网关没起"，不替代总时限。

两个数都做成 `MediaFileHandler` 的构造参数（默认取模块常量 `REVIEW_MERGE_WINDOW = 15.0`、`REVIEW_TOTAL_TIMEOUT = 60.0`），测试用毫秒级值驱动，避免真实等待 15 秒。

### D5. 超时实现：`asyncio.wait` 收口，httpx 只负责建连

- 总时限用 `asyncio.wait(tasks, timeout=remaining)`，到期后逐个 `task.cancel()`，并 `await asyncio.gather(*pending, return_exceptions=True)` 等取消落地，避免留下" cancellation 未处理"的告警。
- httpx 客户端使用 `httpx.Timeout(connect=5.0, read=None, write=None, pool=None)`：只要连接建立，读就交给 60 秒总时限；被 `cancel()` 时 httpx 会关闭连接。
- 不使用 `httpx.Timeout(60)` 当总上限：它是逐操作超时，持续有 token 回来的生成永远不会触发。

### D6. 点评器按调用创建客户端，`PhotoReviewer` 增加可选 `timeout`

`PhotoReviewer` 增加 `timeout: Optional[httpx.Timeout] = None`，仅在它自行创建 `AsyncClient` 时使用；注入 `http_client` 时（测试、CLI）保持调用方说了算。这样 handler 不需要维护共享客户端的生命周期，也不会因为一次超时把连接池置于可疑状态；代价是每张照片多一次 TCP 建连（本地网关，可忽略）。

图片解码改为在服务内部 `await asyncio.to_thread(_encode_image, image_path)`：Pillow 解码是同步的，群聊 9 张并发时不应阻塞事件循环。CLI 行为不变。

被否掉的方案：在 `main()` 创建一个共享 `AsyncClient` 注入 handler——需要在停机时关闭，而它不属于 `BotService` 的职责，收益只有 keep-alive。

### D7. 可选配置与启动探测

```
main():
    config = ReviewConfig.from_env_optional(os.environ)
    if config is None:
        logger.info("Photo review disabled: OPENAI_* not configured")
        reviewer = None
    else:
        reviewer = PhotoReviewer(..., timeout=httpx.Timeout(connect=5.0, read=None))
    pipeline = create_pipeline(..., reviewer=reviewer)
    runner = BotService(..., startup_hook=probe_review_if_configured)
```

- `from_env_optional()` = `try: from_env()` / `except ReviewConfigError: return None`，不复制校验逻辑，`from_env()` 的"缺失即报错"语义原样保留给 CLI。
- `BotService` 新增可选 `startup_hook: Callable[[], Awaitable[None]]`，在 `start()` 中、`client.start()` 之前执行（顺序：信号注册 → hook → 上线通知 → 启动 SDK）。这是通用的启动钩子，不引入对 `photo_review` 的依赖，也自然覆盖未来的 ASGI lifespan。
- hook 由 `main()` 用闭包提供：

```
async def probe_review():
    ok = await probe_gateway(config, logger=logger)   # 3s
    if not ok:
        media_handler.disable_review()                # reviewer = None
```

- `probe_gateway()` 放在 `app/services/photo_review.py`：`GET {base_url}/models/{quote(model, safe="")}`，Bearer 认证，`httpx.Timeout(3.0)`；2xx → `True`，其余/异常 → `False`。日志按 INFO/WARNING 分流，且在 WARNING 里带上状态码或异常类型，不打 API Key。
- 探测失败后**硬禁用**：`reviewer = None`，后续照片不再发请求。这与磁盘探测的"软重试"不同，因为点评是增强项，模型名写错是最常见故障，逐张重试只会让每张照片多等 5 秒；Ollama 晚启动的代价是重启一次进程，可以接受。

被否掉的方案：探测 `GET /models` 拉列表再本地比对——多一步解析且对网关实现更敏感；实测 `/models/{model}` 能精确回答"这个模型存不存在"。

### D8. 多图合并格式与顺序

- 首次回复仍按现有顺序：每张图片的"文件接收成功，已保存为…" + 各自的 EXIF 行。
- 点评块统一由一个 `_format_reviews(reviews: dict[int, str])` 生成：
  - 只有 1 条成功点评 → 直接返回该文本，不加编号；
  - 多条 → 按图片序号升序 `图1：…`、`图3：…`（保留原始序号，方便对上被保存的第几张），换行连接；
  - 0 条 → 返回 `None`，调用方不加任何内容。
- 合并路径：首次回复文本 `+ "\n" + block`，不加「照片点评：」前缀（它紧接 EXIF，读起来是同一条回复的一部分）。
- 补发路径：`照片点评：\n` + block（单条时 `照片点评：` + 文本也可，实现统一为「照片点评：」换行后接块）。
- 点评块在合并路径中位于所有图片的保存行之后，而不是插在每张图的 EXIF 下面——群聊里逐图穿插会让消息更长且更难读。

### D9. 群聊窗口与结束条件

- 多图仍串行下载/保存（现状不变），但在每张保存成功后立即启动它的点评任务；因此串行阶段结束后，前面的点评可能已完成。
- 15 秒窗口从"本批次首次回复文本组装完成"开始计时，整批共用一个定时器。
- 补发阶段只处理仍在运行的任务；已有结果保留在 `_ReviewBatch` 中，最终一起格式化。60 秒从批次启动时算起，补发阶段用 `60 - 已过时间`。
- 部分图片保存失败或重复：不点评（没有落盘路径），其序号不出现在点评块里。

### D10. 关停语义

- 补发任务由 handler 在返回 intent 前创建（等待 `after_reply` 释放的门闩），不在 `_active_tasks` 中，`drain_active_tasks` 不会等它。
- `MediaFileHandler` 用一个独立的 `_review_tasks` 集合持有这些任务，`cancel_tasks()`（`begin_drain()` 会调用）一并取消，避免事件循环关闭时出现"Task was destroyed but it is pending"告警；取消不等待、不补发。
- 合并窗口内的等待仍发生在 SDK 任务里，最坏让 drain 多等至多 15 秒，超过 `drain_active_tasks(timeout=10.0)` 时按现有逻辑放弃并记日志。这是既有机制的自然结果，不为点评单独放宽。
- 发送第二条时若事件循环已在关闭，捕获异常并记 WARNING，不向上抛。

### D11. 测试策略

- **延迟可控的假点评器**：`class FakeReviewer` 内部用 `asyncio.Event` / `asyncio.sleep`，不用真实网络；`MediaFileHandler` 以毫秒级窗口（如 0.05 s）与总时限（如 0.2 s）构造。
- 断言三层：
  1. 窗口内完成 → 1 次 `async_reply_text`（经 `_dispatch` 合并路径），文本包含 EXIF 与点评且无前缀；
  2. 窗口外完成 → 首次回复不含点评，补发任务结束后出现第 2 次发送，且以「照片点评：」开头；
  3. 点评永远不返回 → 总时限后取消，只有 1 次发送，且日志含 WARNING。
- 多图：3 张中 1 张失败 → 点评块出现 `图1：`、`图3：`，不出现 `图2：`；全部失败 → 无第二条。
- 未配置：`reviewer=None` → 与现有用例相同的单条回复，且 `_review_tasks` 为空。
- 探测与配置：`httpx.MockTransport` 覆盖 200 / 404 / 超时；断言请求路径中的模型名已编码、Authorization 头存在；URL 编码断言与真实网关实测一致。
- 全部用例沿用 `tests/test_photo_review.py` 的约束：`grep -c 'setenv\|monkeypatch'` 必须为 0；需要"环境"的测试显式传字典。

## Risks / Trade-offs

- [照片消息的 ACK 最坏多等 15 秒] → 这是"合并成一条"的必然代价；冷加载 8.94 秒仍在窗口内，多数请求表现为 2–9 秒延迟。若不满意，把 `REVIEW_MERGE_WINDOW` 调到 0 即退化为纯两段式，无需改结构。
- [后台第二条消息可能晚到，用户已忘记上下文] → 60 秒总时限收口，并在补发消息上固定「照片点评：」前缀。
- [一组 9 张图并发 9 个 vision 请求，本地模型排队] → 60 秒总时限统一取消；已完成的结果仍可用，不会因为个别卡住而全部丢弃。
- [Ollama 冷加载在 15 秒窗口内完成但推理较慢，首次回复已发出] → 属预期两段式，第二条会带前缀补发。
- [启动探测 200 不代表模型已加载] → 第一次点评可能触发约 9 秒冷加载；已记录在文档与风险中，不引入预热（预热会拖慢启动且占用显存）。
- [停机时正在进行的点评被丢弃] → 明确接受；任务会被取消并在日志留痕。
- [点评文本长度不可控] → 当前提示词实测约 100–130 字，群聊 9 张合计约 1.2k 字，远低于钉钉文本消息上限；本次不做截断。
- [点评器每次新建客户端] → 每张图多一次 TCP 建连，本地网关开销可忽略；换共享客户端需要额外的停机关闭责任。

## Migration Plan

- 未配置 `OPENAI_*` 的部署：行为完全不变，启动日志多一行"未配置，点评已禁用"。
- 已配置但网关/模型不可用：启动 WARNING + 硬禁用，回复与未配置时一致。
- 配置正确：照片回复开始带点评；不需要数据迁移，回滚只需回退代码。
- 建议上线前用 `uv run python -m script.review <一张照片>` 确认网关与模型名，再启动机器人观察日志中的探测结论。

## Open Questions

（无。合并窗口、总时限、前缀、群聊合并与探测失败策略均已定案。）
