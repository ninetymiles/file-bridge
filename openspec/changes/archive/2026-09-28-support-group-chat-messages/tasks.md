## 1. MediaFileHandler 支持 richText 图片处理

- [x] 1.1 将 `MediaFileHandler` 现有单图处理体抽取为内部协程（如 `_process_one_image(download_code, original_filename, default_ext, message, raw_data)`），返回结构化逐图结果（saved/duplicate/failed + 详情）；`picture` 路径改为调用该协程，保持单图单回复行为不变；运行现有 `tests/test_media_file_handler.py` 全部通过
- [x] 1.2 `MediaFileHandler` 支持集合加入 `richText`：直接遍历 `raw_data["content"]["richText"]` 提取所有含 `downloadCode` 的图片段（不依赖 SDK 的 `rich_text_content` 对象）；无图片段时返回 False 放行后续处理器；有图片段时逐张调用 1.1 的协程，缺省文件名按序号 `picture_1.png`、`picture_2.png`...，全部处理完后发送一条汇总回复（逐行列出保存文件名或重复提示），并返回 False 让 CommandHandler 继续解析；新增单测覆盖单图、多图、多图含重复、无图片段四种场景
- [x] 1.3 实现逐张异常隔离：单张下载/保存失败仅记录 failed 状态并继续其余图片，汇总回复包含该张失败提示，handle 不抛异常并返回 False；新增部分失败用例（mock 第一张抛异常、第二张成功）验证第二张仍落盘且回复含失败行

## 2. CommandHandler 支持 richText 文本合并与命令解析

- [x] 2.1 在 `CommandHandler` 内联实现 `_merge_rich_text(segments) -> str`：遍历 segments，text 段中匹配 `^@\S+$` 的独立 @ 提及段跳过、其余拼接，picture 段替换为 `<imgN>`（N 从 1 开始）；补充单测：`[@FileBridge, 重建索引, \n, pic]` → `重建索引\n<img1>`、`[pic, \n, @FileBridge]` → `<img1>\n`、`[pic1, \n, pic2]`（单聊无 @）→ `<img1>\n<img2>`、纯 text richText 正常拼接
- [x] 2.2 `CommandHandler.handle` 新增 `richText` 分支：调用 `_merge_rich_text` 获得合并文本，与 `text` 分支共用后续 `.strip()` 与命令匹配逻辑；合并文本在 DEBUG 级别打印；命中命令则执行并返回 True，否则返回 False；更新 `tests/test_command_handler.py` 中 `@Bot 重建索引` 用例为平台真实形态（` 重建索引` 前导空格、无 @ 前缀），新增 richText 命令触发用例

## 3. Pipeline 流转模型确认

- [x] 3.1 确认 `PipelineHandler._dispatch` 保留短路逻辑（handler 返回 True 终止、False 继续），无需修改；验证 richText 消息经 MediaFileHandler（返回 False）→ CommandHandler（返回 True/False）完整流转

## 4. 文档与整体验证

- [x] 4.1 更新 `README.md`：补充平台投递限制说明（群聊仅 @ 机器人的文本与图片可接收，文件/视频/语音请通过单聊发送）
- [x] 4.2 运行 `uv run pytest` 确认全部用例通过，并运行 `openspec validate support-group-chat-messages --strict` 确认变更草案校验通过
- [x] 4.3 真机验证：在调试群分别 @ 机器人发送文本、单张图片、多张图片、图片+命令组合，核对 richText 段落结构、图片落盘与去重、命令触发均符合 spec
