## 1. 公共预热模块

- [x] 1.1 在 `app/services/disk_warmup.py` 实现 `ensure_storage_ready(probe, on_waking, delay=3.0)` 协程：`probe` 经 `asyncio.to_thread` 执行，与 `asyncio.sleep(delay)` 计时器以两个独立 task + `asyncio.wait(..., return_when=FIRST_COMPLETED)` 竞争；探针先完成则取消计时器静默返回，计时器先到期则 `await on_waking()` 后继续等待探针；最终 `await` 探针并令其异常原样抛出；模块不依赖钉钉 SDK，无业务状态
- [x] 1.2 实现活动文件探针（置于既有落盘职责所在位置，如 `app/utils/file_storage.py`）：覆写 `os.path.join(output_dir, ".activity")` 写入当前时间戳字符串，`flush()` 后 `os.fsync()`，关闭文件；在 `app/main.py` 装配处以 `output_dir` 绑定为零参数可调用对象
- [x] 1.3 编写模块单元测试（假探针用 `asyncio.sleep` / 即时返回 / 抛异常模拟，假回调记录调用）：探针快速返回时回调不被调用；探针超时时回调恰好被调用一次且调用后仍等待探针完成；探针抛异常时异常向调用方传播、快速路径下不调用回调；探针阻塞期间事件循环不被卡住（计时器在虚拟延迟下准时触发）

## 2. Dispatcher 入口接线

- [x] 2.1 在 `app/handlers/message.py` 固化文案常量（如 `WAKING_STORAGE_TEXT = "正在唤醒存储服务，请稍候…"`、`STORAGE_UNAVAILABLE_TEXT = "存储服务暂时不可用，请稍后重试"`），并在 `PipelineHandler.__init__` 注入 `storage_probe`（默认装配为 output 卷探针）
- [x] 2.2 在 `_dispatch` 的 `incoming_message` 解析之后、`_log_received_message` 调用之前插入 `await ensure_storage_ready(...)`；`on_waking` 为 `lambda: self.async_reply_text(WAKING_STORAGE_TEXT, incoming_message)`；探针抛异常时记录 ERROR 日志、发送 `STORAGE_UNAVAILABLE_TEXT` 并 return ACK，不再进入处理器循环
- [x] 2.3 编写模块组合测试：慢探针下唤醒提示先于一切日志与最终回复、快探针下无额外消息、探针异常时回复存储不可用提示且消息不再进入处理链；断言 `_log_received_message` 在探针完成后才执行（日志调用顺序）
- [x] 2.4 验证各消息类型（`text` / `picture` / `file` / `richText` / `audio`）均先经预热再进入处理链；"重建索引"命令冷盘先收唤醒提示、再收索引重建结果

## 3. 装配与启动路径

- [x] 3.1 `app/main.py` 的 `create_pipeline` 处绑定 `storage_probe`（`lambda` 或 `functools.partial` 绑定 `output_dir`）；不改动 `MediaFileHandler`、`CommandHandler`、`rebuild_index` 回调的现有签名与实现

## 4. 全量回归

- [x] 4.1 运行 `uv run pytest`（general 集）确认无回归；重点复核：意图合并裁决与不支持类型兜底行为不变、shutdown drain 对慢探针场景不新增卡死（10 秒上限语义保持）、快探针下热盘路径不新增用户可见消息
