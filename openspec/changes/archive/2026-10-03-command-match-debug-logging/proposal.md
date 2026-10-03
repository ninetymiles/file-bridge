## Why

当前文本命令未命中时全链路静默：子串匹配器没有任何日志；语义匹配器在相似度低于阈值时直接返回 None，把最有调参价值的 best score 与对应短语丢弃；CommandHandler 对"空文本跳过匹配""未命中后走引导回复/因图片静默"等分支也没有记录。线上排查"用户说了什么、为什么没命中"只能靠消息原文人工推断，语义阈值（0.8）是否合理也缺乏数据支撑。

## What Changes

- `SubstringCommandMatcher` 未命中任何短语时输出 DEBUG 日志，记录归一化后的输入文本。
- `SemanticCommandMatcher` 相似度低于阈值时输出 DEBUG 日志，记录归一化文本、最高分短语及其分数、阈值；命中时的日志维持现有 INFO。
- `CommandHandler` 在三个未命中分支补 DEBUG 日志：空文本跳过匹配、未命中且发送引导回复、未命中但消息含图片段保持静默。
- 仅新增诊断日志，不改变任何匹配、分发与回复行为。

## Capabilities

无。本变更仅增加 DEBUG 级可观测性，不引入或修改任何对外行为契约（`.openspec.yaml` 已设置 `skip_specs: true`）。

## Impact

- 代码：`app/services/command_matching/substring.py`、`app/services/command_matching/semantic.py`、`app/handlers/message.py`（CommandHandler）。
- 依赖、配置、数据库、API：无变更。
- 日志量：每条未命中文本消息增加 1-2 条 DEBUG 帧，仅在 `LOG_LEVEL=DEBUG` 时输出，默认 INFO 级别无影响。
