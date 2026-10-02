## MODIFIED Requirements

### Requirement: richText 文本语义合并与命令解析
对于 `richText` 消息，系统 SHALL 将 `content.richText` 列表中的 text 段与图片段合并为单一语义文本字符串：text 段按序拼接（其中匹配 `^@\S+$` 的独立 @ 提及段被移除），图片段替换为 `<imgN>` 占位符（N 为图片序号，从 1 开始）。`text` 类型消息与合并后的 richText 文本 SHALL 经过同一命令解析路径：先剥离全部 `<imgN>` 占位符并折叠空白，再交由当前装配的命令匹配器（默认子串匹配器，或开关启用的语义匹配器，规则由 `semantic-command` 能力定义）判定，命中时按 command id 执行分发表中的回调，无命中时不执行命令。合并与归一化逻辑仅服务于命令解析，不修改原始消息数据。

#### Scenario: richText 文本合并并触发命令
- **WHEN** 群聊收到 `richText` 消息，其 segments 为 `[@FileBridge, 重建索引, \n, pic1]`
- **THEN** 合并后的文本为 `重建索引\n<img1>`，剥离占位符后为 `重建索引`，默认子串匹配器命中"重建索引"命令并执行

#### Scenario: @ 提及在段尾时仍被正确剥离
- **WHEN** 群聊收到 `richText` 消息，其 segments 为 `[pic1, \n, @FileBridge]`
- **THEN** 合并后的文本为 `<img1>\n`，@ 提及被移除；剥离占位符后文本为空，不触发命令匹配

#### Scenario: 单聊 richText 无 @ 提及
- **WHEN** 单聊收到 `richText` 消息，其 segments 为 `[pic1, \n, pic2]`
- **THEN** 合并后的文本为 `<img1>\n<img2>`，无 @ 提及需剥离；剥离占位符后文本为空，不触发命令

#### Scenario: 合并文本用于命令匹配
- **WHEN** `richText` 合并文本经剥离占位符与空白归一化后送入当前匹配器
- **THEN** 默认子串匹配器按短语包含判定；语义开关启用时由语义匹配器按相似度阈值判定；命中则执行对应命令并回复结果，未命中则不执行命令
