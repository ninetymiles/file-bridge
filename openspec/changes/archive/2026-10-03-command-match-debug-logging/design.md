## Context

命令匹配链路当前只有一条命中日志：`CommandHandler` 在 `command_id is not None` 时输出 `INFO Command matched: <id>`。未命中路径无日志；`SubstringCommandMatcher` 内未引入 logger；`SemanticCommandMatcher` 计算了全部相似度但低于阈值时只返回 None。项目日志约定为 `file-bridge` 系列 logger，`LOG_LEVEL=DEBUG` 时其子 logger 的 DEBUG 帧经 root handler（INFO）仍会输出。

## Goals / Non-Goals

**Goals:**
- 未命中时可从 DEBUG 日志还原：用户说了什么、走到了哪个分支
- 语义未命中时记录最高分短语与分数，为阈值调整积累数据
- 默认 INFO 级别零影响，不改变任何行为

**Non-Goals:**
- 不调整匹配算法、阈值与命令目录
- 不引入日志采样、脱敏或结构化日志改造
- 不对诊断日志编写断言测试（遵循项目"诊断日志不作为功能测试断言"约定）

## Decisions

### 1. 日志埋点位置与内容

| 位置 | 触发条件 | DEBUG 内容 |
|------|---------|-----------|
| `substring.py` `match()` | 遍历目录后无命中 | 归一化输入文本 |
| `semantic.py` `_match_blocking()` | best score < 阈值 | 输入文本、最高分短语、分数、阈值 |
| `message.py` `CommandHandler` | normalized 为空 | 空文本跳过匹配（标注 richText 含图片时仍会存档） |
| `message.py` `CommandHandler` | 未命中且无图片段 | 未命中，发送引导回复 |
| `message.py` `CommandHandler` | 未命中但含图片段 | 未命中，媒体消息保持静默 |

匹配成功路径维持现状（CommandHandler 的 INFO），语义 matcher 内部不重复记录命中，避免同一事件两条日志。

### 2. Logger 命名

`substring.py` 与 `semantic.py` 统一使用 `logging.getLogger("file-bridge.command")`（command_matching 包 `__init__.py` 已用 `file-bridge`，子 logger 命名与其风格一致）；CommandHandler 沿用自身 `self.logger`（`app.handlers.message`，由 main 装配时实际传入 `file-bridge` logger）。

### 3. 文本内容直接记录，不做截断

DEBUG 面向运维自查场景，命令文本通常很短；截断反而妨碍排查。若未来接入更敏感场景再单独评估脱敏。

## Risks / Trade-offs

- **[DEBUG 日志量]** 群聊中每条未命中 @ 消息都会产生日志。→ 仅 DEBUG 级别输出，生产默认 INFO 不受影响。
- **[日志与实现耦合]** 埋点分布在 matcher 与 handler 两层。→ matcher 层记录"匹配器看到的输入与判定"，handler 层记录"未命中后的处置分支"，职责不重叠，不做跨层合并。
