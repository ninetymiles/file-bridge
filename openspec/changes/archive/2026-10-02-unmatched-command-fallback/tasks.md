## 1. 兜底文案

- [x] 1.1 在 `app/handlers/message.py` 定义 `FALLBACK_GUIDE_TEXTS` 常量（12 版措辞，覆盖群聊 @ 发图、单聊发图片/文件/视频、自动保存到服务器），人工复核 12 版措辞无重复、无歧义。

## 2. richText 图片段信号

- [x] 2.1 调整 `CommandHandler._merge_rich_text`，在现有单次遍历中额外带出"是否含图片段"布尔值；更新 `test_merge_rich_text_*` 既有测试适配新签名，并验证全部通过。

## 3. 兜底判定与回复

- [x] 3.1 在 `CommandHandler.handle` 中实现兜底谓词（匹配结果为空 且 无图片段），命中时通过 `pipeline.async_reply_text(random.choice(FALLBACK_GUIDE_TEXTS), message)` 回复；确认返回值仍恒为 `False`、空内容（仅 @）同样触发。
- [x] 3.2 改写 `tests/test_command_handler.py`：`test_command_handler_ignores_unmatched_text` 改为断言回复内容属于文案集合；新增仅 @ 无文本、无图片段 richText 未命中、含图片段 richText 抑制回复、非文本类型不回复四个用例；`uv run pytest tests/test_command_handler.py` 全部通过。

## 4. 回归与验证

- [x] 4.1 运行 `uv run pytest`（general 测试集）全部通过，确认模块组合测试中未命中场景行为符合 spec。
- [x] 4.2 运行 `openspec validate --strict`（及 `openspec validate --specs`）无新增错误，确认 delta 与主规范一致。

## 5. 不支持消息类型回复

- [x] 5.1 在 `MediaFileHandler.handle` 入口实现：单聊（`conversationType=1`）收到不在 `SUPPORTED_MSG_TYPES` 的类型时，回复固化的"暂不支持"提示（`audio` 给语音专用措辞，其余给通用措辞），不执行保存，仍返回 `False`；群聊保持静默。
- [x] 5.2 在 `tests/test_media_file_handler.py` 新增用例：单聊 audio 回复语音不支持、单聊未知类型回复通用不支持、群聊未知类型不回复；`uv run pytest tests/test_media_file_handler.py` 全部通过。
- [x] 5.3 运行 `uv run pytest` 全量通过，再运行 `openspec validate unmatched-command-fallback --strict` 无错误。

## 6. 引导回复三维组合改造

- [x] 6.1 在 `app/handlers/message.py` 以三维常量替换 `FALLBACK_GUIDE_TEXTS`：共情前缀（12 版）、清单外壳（12 版，含 `{caps}` 占位）、能力措辞（4 项能力各 6 版，文件/视频均限定单聊）、结尾引导（12 版）；实现清单渲染（每项随机取一条、"• " 条目前缀、仅末行补句号）与回复组装函数；人工复核任意维度组合语义无误导。
- [x] 6.2 调整 `CommandHandler.handle` 回复调用为三维组装：归一化文本非空才附加随机前缀，为空时前缀为空字符串直接回复能力清单；判定谓词、抑制规则与返回值不变。
- [x] 6.3 改写 `tests/test_command_handler.py` 引导相关用例：打桩 `random.choice` 验证拼接顺序（前缀-主体-结尾）、空文本场景断言回复不含任何前缀候选与"听不懂"类表述、成员关系断言覆盖四个候选集合、含图片段抑制用例保留；`uv run pytest tests/test_command_handler.py` 全部通过。
- [x] 6.4 运行 `uv run pytest` 全量通过，再运行 `openspec validate unmatched-command-fallback --strict` 无错误。
