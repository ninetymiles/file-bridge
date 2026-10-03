## 1. ReplyIntent 模型与 Handler 基类签名

- [x] 1.1 在 `app/handlers/message.py` 定义 `ReplyTier`（`IntEnum`，仅表达投递优先级通用语义：`PRIMARY = 100` 高优先级、`SECONDARY = 200` 低优先级，数值越小优先级越高，枚举值保留间隔以便未来插入中间层级）与 `ReplyIntent` 数据类（`tier` + `text`），将 `BaseMessageHandler.handle` 返回类型由 `bool` 改为 `Optional[ReplyIntent]`；`CommandHandler`、`MediaFileHandler` 同步调整签名并暂时返回 `None`，`PipelineHandler._dispatch` 暂改为忽略返回值，验证 `uv run pytest` 中不依赖回复行为的用例通过（回复断言类用例允许暂时失败，在任务 4 修复）

## 2. CommandHandler 意图化

- [x] 2.1 将 `CommandAction` 类型改为 `Callable[..., Awaitable[str]]`，`app/main.py` 中 `rebuild_index` 回调改为返回结果文本、不再调用 `pipeline.async_reply_text`；`CommandHandler` 命中命令时以回调返回文本构造 `PRIMARY` 意图返回，验证"重建索引"命令的模块组合测试断言回复文本与索引清理计数一致
- [x] 2.2 删除 `CommandHandler` 中含图抑制逻辑（`has_picture` 分支）：未命中命令时无条件返回 `SECONDARY` 意图（措辞仍由 `build_guide_reply` 生成，空文本空前缀规则不变），非 `text`/`richText` 类型返回 `None`；编写单元测试覆盖命中→PRIMARY、未命中→SECONDARY、空文本未命中→SECONDARY（空前缀）、非文本类型→None 四个分支

## 3. MediaFileHandler 意图化

- [x] 3.1 `MediaFileHandler` 对 `picture`/`video`/`file`/`richText` 的处理结果（保存成功含元数据行、重复、失败、取消）改为返回 `PRIMARY` 意图，不再调用 `pipeline.async_reply_text`；删除不支持类型分支（含 `msgtype not in SUPPORTED_MSG_TYPES` 的回复逻辑），改为返回 `None`；缺失 `downloadCode` 时同样返回 `None`；调整既有媒体保存测试，断言返回值意图内容而非 reply_text 调用

## 4. Dispatcher 汇总合并与兜底

- [x] 4.1 `PipelineHandler._dispatch` 改为收集全部处理器的非空意图：取最高优先级层级（`PRIMARY` 优先于 `SECONDARY`），该层级全部意图文本按处理器顺序以 `"\n"` 合并为一条消息通过 `async_reply_text` 发送，更低层级一律抑制；全部为空时按"不支持消息类型的明确回复"兜底（单聊 `audio`→`UNSUPPORTED_AUDIO_TEXT`，单聊其他→`UNSUPPORTED_TYPE_TEXT`，群聊→静默 ACK），`UNSUPPORTED_AUDIO_TEXT`/`UNSUPPORTED_TYPE_TEXT` 常量上移至 Dispatcher 侧；编写模块组合测试验证：单聊 `text` 未命中仅收到一条引导（双回复回归）、`richText` 含图+命令命中合并为一条回复、含图未命中仅收到保存结果、单聊 `audio` 与未知类型各收到一条对应不支持提示、缺失 `downloadCode` 的 `picture` 收到不支持提示、群聊无响应消息静默 ACK

## 5. 全量回归

- [x] 5.1 运行 `uv run pytest`（general 集）与 `uv run pytest -m semantic`（如本地具备模型条件），确认无回归；检查 `_log_received_message`、取消令牌（`cancelled` 状态回复）等既有行为在新链路下保持不变
