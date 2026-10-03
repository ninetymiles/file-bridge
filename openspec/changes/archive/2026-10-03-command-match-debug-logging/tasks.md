## 1. 匹配器层埋点

- [x] 1.1 `substring.py` 引入 `file-bridge.command` logger，遍历目录无命中时输出 DEBUG（归一化输入文本），运行现有 `test_command_matching.py` 确认无回归
- [x] 1.2 `semantic.py` 引入 `file-bridge.command` logger，best score 低于阈值时输出 DEBUG（输入文本、最高分短语、分数、阈值）；不新增命中日志

## 2. Handler 层埋点

- [x] 2.1 `CommandHandler` 在 normalized 为空跳过匹配时输出 DEBUG
- [x] 2.2 `CommandHandler` 在未命中且无图片段（发引导回复）与未命中但含图片段（静默）两个分支分别输出 DEBUG，说明最终走向

## 3. 验证

- [x] 3.1 运行 `uv run pytest` 确认 general 测试集全部通过（不新增日志断言）
- [x] 3.2 运行 `openspec validate --changes command-match-debug-logging --strict` 通过
- [x] 3.3 `LOG_LEVEL=DEBUG` 启动应用，分别发送不命中文本、空文本 @、带图片的 @ 消息，确认三类 DEBUG 日志内容正确；切回 INFO 确认无输出
