## Context

See proposal.md - Why。当前消息处理链为 `DingTalkStreamClient.route_message()` → `PipelineHandler.process(callback)` → 顺序执行 `MediaFileHandler`、`CommandHandler`（见 `app/handlers/message.py`）。已确认的平台与代码事实：

- 钉钉平台投递矩阵（线上实测 + 官方文档）：
  - 单聊投递 `text`/`picture`/`video`/`file`/`richText`；多图直接选图发送会被平台拆为多条独立 `picture` 消息，加入输入框后发送则合并为一条 `richText`。
  - 群聊仅投递 @ 机器人的 `text` 与 `richText`；群聊图片在 `content.richText` 列表中以 `{type: picture, downloadCode: ...}` 段落投递；群聊 `file`/`video`/`audio` 平台不投递。
- 群聊 `text` 消息中任意位置的 `@机器人名` 均由钉钉平台自动剥离，原位保留空白字符（@ 在开头则 `text.content` 为 `" hello"`，@ 在末尾则为 `"hello world  "`），无需应用层归一化。
- `richText` 中 @ 提及以独立 text 段形式存在，位置不固定（可在段首 `[@FileBridge, text, pic]` 或段尾 `[pic, @FileBridge]`）。
- SDK 已解析 `ChatbotMessage.rich_text_content.rich_text_list`，但其 `from_dict()` 在遍历到 `msgtype` 键时即时读取 `d['content']`，对键顺序有隐含依赖；原始字典 `raw_data` 始终完整可用。
- `save_file()` 命名含毫秒时间戳与撞名自增计数器，同消息多图不会撞名。
- 当前 pipeline 为短路模型：handler 返回 `True` 终止链，`False` 继续流转。

## Goals / Non-Goals

**Goals:**

- `MediaFileHandler` 支持 `richText` 图片段：多图逐张走既有下载/去重/落盘/入库流程，一条汇总回复。
- `CommandHandler` 支持 `richText`：将文本段合并为语义化纯文本（剥 @、图片→`<imgN>`），执行命令解析，实现 richText 中指令可触发。
- `richText` 消息同时完成图片保存与命令解析，两个 handler 各自独立解析 `raw_data`，无共享中间字段、无顺序依赖。
- 不改变单聊 `picture`/`video`/`file` 既有处理行为与去重语义。

**Non-Goals:**

- 不实现群聊文件/视频/语音接收（平台不投递，无回调可处理）。
- 不新增群内"文件请单聊发送"主动引导文案（后续产品决策）。
- 不处理日志配置与诊断日志，已拆至独立变更 `fix-logging-configuration`。
- 不改动 SDK 本体，不 pin/升级 `websockets` 版本。
- 不为未来向量检索/LLM 预留图片序号到 downloadCode 的映射结构（当前无此需求，届时从 segments 重建即可）。

## Decisions

### 决策 1：群聊 text 消息 @ 由平台任意位置剥离，应用层不做归一化

线上实测确认：群聊 `text` 消息中任意位置的 `@机器人名` 均被钉钉平台移除，原位保留空白字符（@ 在开头则剩前导空格，@ 在末尾则剩尾随空格）。`CommandHandler` 已对读取的 content 执行 `.strip()`，前后空白均被自然处理。因此本变更不引入任何 @ 剥离逻辑。

- 备选 A：在 `process()` 入口手动剥离 @ 前缀。被否：平台已剥离，手动逻辑冗余且可能与平台行为不一致。
- 仅对 `text` 类型生效；`richText` 的 @ 提及在文本合并阶段处理（见决策 2）。

### 决策 2：richText 由两个 handler 独立处理，pipeline 保留短路但默认流转

`richText` 消息需要同时完成图片保存与命令解析，采用两个 handler 各自独立解析 `raw_data` 的方式，不通过中间字段传递结果：

**MediaFileHandler（图片保存）**：
- 支持集合加入 `richText`。直接遍历 `raw_data["content"]["richText"]`，取所有含 `downloadCode` 键的段落（不依赖 SDK 的 `rich_text_content` 对象）。
- 将现有单图处理体抽取为内部协程 `_process_one_image(download_code, original_filename, default_ext, message, raw_data)`，返回结构化逐图结果（saved / duplicate / failed + 详情），`picture` 路径与 `richText` 路径共用。
- `richText` 无图片段 → `return False` 放行后续处理器；有图片段 → 逐张处理，全部完成后**一条**汇总回复（每张一行），然后 `return False` 让 `CommandHandler` 继续解析命令。
- 逐图独立 try/except：单张失败记录 failed 状态并继续其余图片，整条消息不抛未捕获异常。
- `richText` 多图缺省文件名按序号命名为 `picture_1.png`、`picture_2.png`……

**CommandHandler（文本合并与命令解析）**：
- 新增 `richText` 支持。合并逻辑内联为私有方法 `_merge_rich_text(segments) -> str`，规则：
  1. 遍历 segments，`img_counter` 从 0 开始。
  2. text 段：若文本匹配 `^@\S+$`（独立 @ 提及段）则跳过；否则拼接到结果。
  3. picture 段：`img_counter += 1`，拼接 `f"<img{img_counter}>"`。
  4. 返回合并后的字符串。
- 对 `text` 消息读 `message.text.content`；对 `richText` 消息读 `_merge_rich_text()` 的结果；随后执行相同的 `.strip()` 与命令匹配。
- 合并后的文本在 DEBUG 级别打印，便于诊断。
- 匹配到命令则执行并 `return False`（允许后续处理器继续处理同一条消息）；未匹配则 `return False`。

**Pipeline 流转模型**：
- 保留短路机制接口：handler 返回 `True` 终止链，`False` 继续。该接口为未来复杂功能预留，当前变更中所有 handler 均返回 `False`。
- handler 默认返回 `False`，确保每条消息可流转到所有 handler 处理。
- `richText` 场景下：`MediaFileHandler` 保存图片后返回 `False` → `CommandHandler` 解析命令后返回 `False`。两个 handler 均独立读取 `raw_data`，无顺序依赖。
- `picture`/`video`/`file` 场景下：`MediaFileHandler` 处理完毕返回 `False`，`CommandHandler` 运行但因非文本类型返回 `False`。

**<imgN> 占位符设计**：XML 标签风格，正则 `<img\d+>` 易提取；LLM 可理解 `<img1>` 指代第一张图片；不与用户普通文本冲突。为后续向量检索与 LLM 语义推理预留统一文本表示。

### 决策 3：平台限制只做规范化，不做补偿逻辑

群聊收不到文件/视频/语音是平台投递侧限制，代码无法感知"用户曾经尝试发文件"，因此不做轮询、不做伪触发，仅在 spec/README 中写明限制与"文件请单聊发送"的使用说明。

## Risks / Trade-offs

- [@ 剥离规则假设 @ 提及为独立 segment 且不含空格] → 线上实测确认钉钉将 @ 渲染为独立 text 段（`@FileBridge`），正则 `^@\S+$` 可准确剥离；若未来平台改为 `@机器人 名字` 形式，正则需调整为匹配开头至首个空白。
- [多图汇总回复可能超过消息长度上限] → 单条富文本图片数量实际很小，当前不做分条；若日后出现超长，再按条数切分回复。
- [两个 handler 独立解析 richText 存在重复遍历] → 遍逻辑不同（一取 downloadCode、一合并文本），无实际重复开销；符合 SRP，避免跨 handler 耦合。

## Migration Plan

1. 无数据迁移、无新增依赖。
2. 回滚：还原本变更代码即可，不涉及数据与配置残留。
