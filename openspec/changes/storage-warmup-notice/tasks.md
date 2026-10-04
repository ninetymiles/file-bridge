## 1. 公共预热模块

- [ ] 1.1 在 `app/services/disk_warmup.py` 实现 `ensure_storage_ready(probe, on_waking, delay=3.0)` 协程：`probe` 经 `asyncio.to_thread` 执行，与 `asyncio.sleep(delay)` 计时器以两个独立 task + `asyncio.wait(..., return_when=FIRST_COMPLETED)` 竞争；探针先完成则取消计时器静默返回，计时器先到期则 `await on_waking()` 后继续等待探针；最终 `await` 探针并令其异常原样抛出；模块不依赖钉钉 SDK，无业务状态
- [ ] 1.2 实现活动文件探针（置于既有落盘职责所在位置，如 `app/utils/file_storage.py`）：覆写 `os.path.join(output_dir, ".activity")` 写入当前时间戳字符串，`flush()` 后 `os.fsync()`，关闭文件；在 `app/main.py` 装配处以 `output_dir` 绑定为零参数可调用对象
- [ ] 1.3 编写模块单元测试（假探针用 `asyncio.sleep`/即时返回/抛异常模拟，假回调记录调用）：探针快速返回时回调不被调用；探针超时时回调恰好被调用一次且调用后仍等待探针完成；探针抛异常时异常向调用方传播、快速路径下不调用回调；探针阻塞期间事件循环不被卡住（计时器在虚拟延迟下准时触发）

## 2. 文件消息链路接线

- [ ] 2.1 在 `app/handlers/message.py` 固化唤醒提示文案常量（如 `WAKING_STORAGE_TEXT = "正在唤醒存储服务，请稍候…"`）；`MediaFileHandler.handle` 在确认存在 `download_code` 之后、`_process_one_image` 调用之前执行一次 `ensure_storage_ready`，`on_waking` 为 `lambda: pipeline.async_reply_text(WAKING_STORAGE_TEXT, message)`；探针/提示依赖通过构造函数注入（默认装配为 output 卷探针），缺失 `downloadCode` 分支保持不预热
- [ ] 2.2 `_handle_rich_text` 在过滤出非空 `picture_segments` 之后、逐张处理循环之前执行一次预热；后续 `_process_one_image` 不再重复预热；无图片段的 richText 不预热
- [ ] 2.3 编写/调整单元测试：单聊文件消息快探针下仅返回最终意图、无额外 reply_text 调用；慢探针下先收到一次唤醒提示文本、再收到保存成功意图回复；richText 多图慢探针下唤醒提示仅发送一次；无 downloadCode、无图片段场景下探针零调用

## 3. 重建索引命令接线

- [ ] 3.1 将 `CommandAction` 类型签名扩展为 `Callable[[ChatbotMessage, dict, "PipelineHandler"], Awaitable[str]]`，`CommandHandler` 命中调用处透传自身收到的 `pipeline`；同步更新既有命令回调与相关测试
- [ ] 3.2 `app/main.py` 的 `rebuild_index` 闭包接收 `pipeline` 参数，在 `metadata_store.async_rebuild_index()` 前执行一次 `ensure_storage_ready`，`on_waking` 通过 `pipeline.async_reply_text` 发送同一固定提示；返回文本保持现有"索引重建完成…"措辞不变
- [ ] 3.3 编写模块组合测试：重建索引命令在快探针下只有结果回复；慢探针下先收到唤醒提示、再收到索引重建结果，且返回文本中的清理/剩余计数与实际重建一致

## 4. 全量回归

- [ ] 4.1 运行 `uv run pytest`（general 集）确认无回归；重点复核：text/audio/无图片段 richText 不产生探针调用与 `.activity` 写入、意图合并裁决与不支持类型兜底行为不变、shutdown drain 对慢探针场景不新增卡死（10 秒上限语义保持）
