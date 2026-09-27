## 1. 群聊文本 @ 前缀归一化

- [ ] 1.1 在 `app/handlers/message.py` 实现 @ 前缀剥离纯函数（如 `strip_robot_at_prefix(content)`：去开头空白 → 去首个 `@提及段` 及紧随空白 → 其余原样保留），并补充单测：`@机器人名 重建索引` → `重建索引`、无前缀文本不变、正文中间的 `@张三` 保留、空串与 None 安全处理
- [ ] 1.2 在 `PipelineHandler.process()` 中接入归一化：仅当 `conversation_type=="2"` 且消息为 `text` 且 `is_in_at_list` 为真时调用，结果同时写回 `message.text.content` 与 `raw_data["text"]["content"]`；在 `tests/test_pipeline.py` 增加端到端用例：群聊 payload（带 `conversationType=2`、`isInAtList=True`、`text.content="@机器人名 1+2"`）经 process 后 CalcBotFallbackHandler 能正确算出结果并回复，且单聊消息内容不被改写

## 2. richText 图片处理

- [ ] 2.1 将 `MediaFileHandler` 现有单图处理体抽取为内部协程（如 `_process_one_image(download_code, original_filename, default_ext, message, raw_data)`），返回结构化逐图结果（saved/duplicate/failed + 详情）；`picture` 路径改为调用该协程，保持单图单回复行为不变；运行现有 `tests/test_media_file_handler.py` 全部通过
- [ ] 2.2 `MediaFileHandler` 支持集合加入 `richText`：直接遍历 `raw_data["content"]["richText"]` 提取所有含 `downloadCode` 的图片段（不依赖 SDK 的 `rich_text_content` 对象）；无图片段时返回 False 放行后续处理器；有图片段时逐张调用 2.1 的协程，缺省文件名按序号 `picture_1.png`、`picture_2.png`...，全部处理完后发送一条汇总回复（逐行列出保存文件名或重复提示）；新增单测覆盖单图、多图、多图含重复、无图片段四种场景
- [ ] 2.3 实现逐张异常隔离：单张下载/保存失败仅记录 failed 状态并继续其余图片，汇总回复包含该张失败提示，handle 不抛异常并返回 True；新增部分失败用例（mock 第一张抛异常、第二张成功）验证第二张仍落盘且回复含失败行

## 3. 文档与整体验证

- [ ] 3.1 更新 `README.md`：补充平台投递限制说明（群聊仅 @ 机器人的文本与图片可接收，文件/视频/语音请通过单聊发送）；`LOG_LEVEL` 环境变量说明不在本变更范围，归 `fix-logging-configuration`
- [ ] 3.2 运行 `uv run pytest` 确认全部用例通过，并运行 `openspec validate support-group-chat-messages --strict` 确认变更草案校验通过
- [ ] 3.3 真机验证（前提：`fix-logging-configuration` 已合入）：以 `LOG_LEVEL=DEBUG` 启动，在调试群分别 @ 机器人发送文本、单张图片、多张图片，借助其回调头与完整消息体日志核对 @ 前缀的精确字面量与 richText 段落结构，回答 design.md 的 Open Question 并据此最终确认/微调剥离函数实现；验证群聊图片落盘、去重与汇总回复均符合 spec
