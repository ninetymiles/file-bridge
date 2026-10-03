## Context

当前消息处理链路采用短路责任链：处理器返回 `True` 终止处理链，返回 `False` 继续流转。`CommandHandler` 与 `MediaFileHandler` 各自在其 handle 方法中直接调用 `pipeline.async_reply_text` 发送回复。这导致两个问题：

1. 单聊 `text` 消息未命中命令时，`CommandHandler` 返回 `False`，`MediaFileHandler` 因 `msgtype` 不在 `SUPPORTED_MSG_TYPES` 中进入不支持类型分支，发送第二条"暂不支持该类型"回复。
2. `MediaFileHandler` 承担了对 `audio` 等不支持类型的回复职责，回复逻辑与媒体保存职责混合；`CommandHandler` 则需通过 `has_picture` 标志抑制未命中的引导回复，形成处理器间的隐式耦合。

## Goals / Non-Goals

**Goals:**
- 处理器返回意图而非 `bool`，回复生成集中至 Dispatcher。
- 根除双回复问题：不同优先级的回复意图由 Dispatcher 按层级规则统一裁决。
- 处理器职责单一：每个处理器只负责"我做了什么/我建议什么"，不操心"我应不应该发"。

**Non-Goals:**
- 不改动命令解析逻辑（`normalize_command_text`、`match`）、命令分发表、命令措辞。
- 不改动媒体下载/去重/落盘/元数据提取流程及其内部实现。
- 不改动 `richText` 文本合并与 `<imgN>` 占位符规则。
- 不引入新的外部依赖。

## Decisions

### Decision 1: ReplyIntent 与 ReplyTier 的通用化定义

采用不可变意图对象 `ReplyIntent(tier: ReplyTier, text: str)`。`None` 表示"该消息与当前处理器职责无关"。

`ReplyTier` 定义为 `IntEnum`，仅表达"投递优先级"这一通用语义，不耦合任何内容或业务类型：

```python
class ReplyTier(IntEnum):
    PRIMARY = 100    # 高优先级：确定性内容（当前用于保存结果、命令执行结果）
    SECONDARY = 200  # 低优先级：建议性内容（当前用于命令未命中引导）
```

数值越小优先级越高；枚举值保留间隔，未来插入中间层级（如错误通知）时无需重编号。成员注释仅说明当前用途，不构成层级语义。

- **Rationale**: 若命名为 `ANSWER`/`GUIDANCE`，层级即与内容类型耦合（"答复"暗示命令结果、"引导"暗示帮助清单）；未来新增内容类型时将被迫向枚举塞入业务语义，或把新内容塞进语义不符的层级。通用优先级命名使 Dispatcher 仲裁规则只依赖层级序关系，新增内容类型或新增层级时仲裁逻辑零改动。`text` 保持 `str`：当前业务仅有文本回复，不为未来内容类型预留泛型载荷。
- **Alternatives considered**: ① `ANSWER`/`GUIDANCE` 业务命名——拒绝，层级与内容耦合；② 纯整数优先级、无枚举——拒绝，失去意图可读性；③ 连续枚举值 `1`/`2`——拒绝，未来插入中间层级需重编号。

### Decision 2: 所有处理器运行至完成，不短路

`PipelineHandler._dispatch` 遍历全部 handlers，收集全部非空意图，随后按规则合并。

- **Rationale**: 消除执行顺序依赖。当前 `richText` 含图+命令依赖 "MediaFileHandler 先、CommandHandler 后" 的顺序才能正确；变更后两者均可返回意图，顺序无关。
- **Trade-off**: 对于纯文本消息，`MediaFileHandler` 仍需判断 `msgtype` 并返回 `None`，多了一次无意义调用。收益远大于成本。

### Decision 3: Dispatcher 层级裁决规则（通用化）

收集全部 `ReplyIntent` 后：
1. 取所有意图中优先级最高的层级（`ReplyTier` 数值最小者）。
2. 将该层级全部意图的 `text` 按处理器顺序以 `"\n"` 合并为一条消息发送；更低层级一律抑制不发送。
3. 若全部返回 `None`：Dispatcher 按消息类型兜底——单聊 `audio` → 专用语音不支持提示；单聊其他 → 通用不支持提示；群聊 → 静默 ACK。

- **Rationale**: 裁决规则只依赖层级序关系，不依赖各层级的业务含义；当前两级行为（`PRIMARY` 合并、`SECONDARY` 让位）是该通用规则的特例。低层级让位恰好替代了当前 `CommandHandler` 中 `has_picture` 的自抑制逻辑，但由 Dispatcher 统一裁决，职责边界更清晰。未来新增层级、或将新内容类型归入现有层级时，本规则无需修改。
- **Alternatives considered**: 按层级硬编码分支（`PRIMARY` 合并、`SECONDARY` 取首条）——拒绝，新增层级需改动 Dispatcher；为每个层级定义独立合并策略——拒绝，当前无差异化合并需求，属过度设计。

### Decision 4: 常量和回复发送统一上移至 PipelineHandler

`UNSUPPORTED_AUDIO_TEXT`、`UNSUPPORTED_TYPE_TEXT` 从 `MediaFileHandler` 模块移至 `PipelineHandler`（或模块级常量），`async_reply_text` 仅在 Dispatcher 中调用。

- **Rationale**: 回复是 Dispatcher 的职责，常量应与其共处。

### Decision 5: 命令回调返回文本而非自行回复

`CommandAction` 签名由 `Awaitable[None]` 改为 `Awaitable[str]`：命令执行回调（如 `rebuild_index`）返回完整措辞的结果文本，由 `CommandHandler` 包装为 `PRIMARY` 级意图。回调不再持有 `pipeline` 参数调用 `async_reply_text`。

- **Rationale**: 这是"处理器不自行发送回复"原则在命令回调层的自然延伸；若不收回，Dispatcher 无法对命令结果执行合并。

### Decision 6: Handler 装配顺序保留但不再语义相关

`create_pipeline` 仍保持 `CommandHandler` → `MediaFileHandler` 的默认顺序，但意图合并时按遍历顺序拼接最高优先级层级的文本。

- **Rationale**: 保持最小改动。虽然顺序不再影响行为正确性，但合并回复的文本顺序仍由装配顺序决定。

## Risks / Trade-offs

- **[Risk] `richText` 同时含多图失败+命令结果时合并消息较长** → **Mitigation**: 合并方式保持与当前多条独立消息的总信息量一致，无额外膨胀。若未来消息过长可考虑截断，但当前场景罕见。
- **[Risk] `BaseMessageHandler.handle` 签名变更需同步所有子类** → **Mitigation**: 当前仅两个子类（`CommandHandler`、`MediaFileHandler`），变更范围极小。
- **[Risk] 测试需大规模重写** → **Mitigation**: 现有 `create_pipeline` 组合测试主要断言最终回复内容；重构后断言目标不变，仅需调整 setup（如不再通过 `CommandHandler` 的 `has_picture` 分支判断回复存在性）。

## Migration Plan

纯代码级重构，无数据迁移、无配置变更、无部署序列依赖。上线后观察日志确认单聊文本消息仅产生一条回复即可。
