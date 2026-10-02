# message-pipeline Specification

## Purpose

定义钉钉回调消息进入机器人后的统一接收入口规范，涵盖平台消息投递范围适配、平台消息结构约定、`richText` 图片段提取处理、`richText` 文本语义合并与命令解析、pipeline 流转模型，保障群聊 @ 机器人与单聊场景获得一致的消息处理体验。

以下消息结构均来自线上实测（已脱敏），作为后续设计与实现的参考基准。

## Requirements

### Requirement: 平台消息投递范围适配
系统 SHALL 按钉钉平台的实际投递范围处理回调消息：单聊（`conversationType=1`）平台投递 `text`、`picture`、`video`、`file`、`audio` 与 `richText` 类型，其中系统保存 `picture`、`video`、`file` 与 `richText` 图片段，`audio` 不保存（按"不支持消息类型的明确回复"要求回复）；群聊（`conversationType=2`）投递 @ 机器人的 `text` 消息与 `richText` 消息，其中群聊图片以 `richText` 的图片段形式投递。群聊中 `file`、`video`、`audio` 的消息内容 MUST NOT 被假设为可获取（平台不投递内容）；其中群聊视频会额外产生一条仅含 @ 段与换行、不含任何图片段的 `richText` 帧，系统按空文本处理。系统 MUST NOT 在应用层对"消息是否发给机器人"做分拣——平台已保证群聊消息均来自 @ 机器人，所有到达回调入口的消息均直接进入处理链。

#### Scenario: 群聊图片以 richText 投递
- **WHEN** 群成员在群聊中 @ 机器人并发送图片
- **THEN** 系统收到的消息类型为 `richText`，图片二进制的 `downloadCode` 位于 `content.richText` 列表中 `type=picture` 的段落内，而非顶层 `picture` 消息

#### Scenario: 群聊文件、视频、语音不投递
- **WHEN** 群成员在群聊中 @ 机器人发送文件、视频或语音
- **THEN** 钉钉平台不向机器人投递该消息的内容与下载码，系统不执行保存；文件与视频的接收能力仅在单聊中可用（群聊视频的空帧行为见下一 Scenario）

#### Scenario: 群聊视频产生空 richText 帧
- **WHEN** 群成员在群聊中 @ 机器人发送一条视频（Android 端实测）
- **THEN** 系统额外收到一条 `richText` 消息，仅包含 @ 机器人的 text 段与一个换行 text 段，不含图片段；归一化后文本为空，系统按"未命中文本兜底引导"以空前缀直接回复能力清单

#### Scenario: 不对已投递消息做 @ 分拣
- **WHEN** 任意群聊回调消息到达处理入口
- **THEN** 系统直接进入处理链，不以 `isInAtList` 字段或 @ 列表作为"是否处理该消息"的判断门槛

#### Scenario: 不含可处理内容的消息正常 ACK
- **WHEN** 系统收到不含图片段、且不含可识别文本指令的消息（如无图片段的 `richText`）
- **THEN** 系统正常确认回调，不触发文件保存流程，不因此报错或重连，并按"未命中文本兜底引导"要求回复一条使用引导

### Requirement: 平台消息结构约定
系统 SHALL 以下列线上实测的消息结构为基准进行解析。所有消息均通过 `callback.data` 原始字典访问，不依赖 SDK 对象模型的字段映射。

#### Scenario: 单聊 text 消息结构
- **WHEN** 用户在单聊中发送纯文本 "hello"
- **THEN** 回调消息结构为（脱敏）：
  ```json
  {
    "conversationType": "1",
    "msgtype": "text",
    "text": { "content": "hello" },
    "senderNick": "<nick>",
    "senderStaffId": "<staff_id>",
    "senderId": "<sender_id>",
    "chatbotUserId": "<chatbot_user_id>"
  }
  ```
  单聊 text 消息无 `atUsers`、无 `isInAtList` 字段，`text.content` 即用户原始输入。

#### Scenario: 群聊 text 消息 @ 前缀被平台剥离
- **WHEN** 用户在群聊中发送 "@机器人 hello"（@ 在开头）
- **THEN** 回调消息 `text.content` 为 `" hello"`（前导空格，`@机器人名` 已被平台移除），且 `isInAtList=true`、`atUsers` 包含机器人 `dingtalkId`：
  ```json
  {
    "conversationType": "2",
    "msgtype": "text",
    "text": { "content": " hello" },
    "isInAtList": true,
    "atUsers": [{ "dingtalkId": "<chatbot_user_id>" }],
    "chatbotUserId": "<chatbot_user_id>"
  }
  ```

#### Scenario: 群聊 text 消息 @ 在任意位置均被剥离
- **WHEN** 用户在群聊中发送 "hello world @机器人"（@ 在末尾）
- **THEN** 回调消息 `text.content` 为 `"hello world  "`（尾随空格，`@机器人名` 已被平台移除）。平台对 `text` 消息中任意位置的机器人 @ 提及均执行剥离，剥离后原位保留空白字符。

#### Scenario: 群聊 richText 消息结构（@ 在段首）
- **WHEN** 用户在群聊中发送 "@机器人 abcd [图1] [图2]"
- **THEN** 回调消息 `msgtype` 为 `richText`，`content.richText` 为有序段落列表：
  ```json
  {
    "conversationType": "2",
    "msgtype": "richText",
    "isInAtList": true,
    "atUsers": [{ "dingtalkId": "<chatbot_user_id>" }],
    "content": {
      "richText": [
        { "text": "@FileBridge" },
        { "text": "abcd" },
        { "text": "\n" },
        { "type": "picture", "downloadCode": "<download_code>", "pictureDownloadCode": "<picture_download_code>" },
        { "text": "\n" },
        { "type": "picture", "downloadCode": "<download_code>", "pictureDownloadCode": "<picture_download_code>" }
      ]
    }
  }
  ```

#### Scenario: 群聊 richText 消息结构（@ 在段尾）
- **WHEN** 用户先选图再 @ 机器人，发送 "[图1] @机器人"
- **THEN** `content.richText` 中 @ 提及段位于列表末尾：
  ```json
  {
    "conversationType": "2",
    "msgtype": "richText",
    "content": {
      "richText": [
        { "type": "picture", "downloadCode": "<download_code>" },
        { "text": "\n" },
        { "text": "@FileBridge" }
      ]
    }
  }
  ```
  @ 提及在 `richText` 中始终以独立 text 段形式存在，位置不固定（可在段首或段尾）。

#### Scenario: 单聊 richText 多图消息结构
- **WHEN** 用户在单聊中将多张图片加入输入框后发送
- **THEN** 回调消息为单条 `richText`，包含多个 picture 段（无 @ 提及段）：
  ```json
  {
    "conversationType": "1",
    "msgtype": "richText",
    "content": {
      "richText": [
        { "type": "picture", "downloadCode": "<download_code>" },
        { "text": "\n" },
        { "type": "picture", "downloadCode": "<download_code>" }
      ]
    }
  }
  ```

#### Scenario: 单聊多图直接发送拆分为多条 picture 消息
- **WHEN** 用户在单聊中直接选择多张图片发送（不经过输入框）
- **THEN** 平台将多张图片拆分为多条独立的 `picture` 消息回调，每条消息仅含一张图片的 `downloadCode`：
  ```json
  {
    "conversationType": "1",
    "msgtype": "picture",
    "content": {
      "downloadCode": "<download_code>",
      "pictureDownloadCode": "<picture_download_code>"
    }
  }
  ```

#### Scenario: 图片消息无 fileName 字段
- **WHEN** 系统解析 `picture` 消息或 `richText` 的图片段
- **THEN** 图片数据中不包含 `fileName` 字段，系统 SHALL 直接使用缺省文件名（`picture.png`、`picture_N.png`）与缺省扩展名（`.png`）落盘，不尝试从负载读取 `fileName`

#### Scenario: file 消息含 fileName 字段
- **WHEN** 系统解析单聊 `file` 消息
- **THEN** 负载的 `content.fileName` 字段包含用户原始文件名，系统 SHALL 从中提取文件名与扩展名用于落盘与元数据记录

#### Scenario: picture 段含两个下载码字段
- **WHEN** 系统解析 `richText` 或 `picture` 消息中的图片
- **THEN** 每个图片段同时包含 `downloadCode`（用于换取下载链接）与 `pictureDownloadCode` 两个字段，系统 SHALL 使用 `downloadCode` 字段换取下载链接

#### Scenario: 群聊 atUsers 标识机器人被 @
- **WHEN** 群聊消息（`text` 或 `richText`）到达回调入口
- **THEN** 若机器人被 @，`atUsers` 数组中包含 `{"dingtalkId": "<chatbot_user_id>"}`，且该 `dingtalkId` 与 `chatbotUserId` 字段值一致；`isInAtList` 为 `true`

### Requirement: richText 图片提取与逐张处理
系统 SHALL 从 `richText` 消息的 `content.richText` 列表中提取全部包含 `downloadCode` 的图片段，对每张图片独立执行既有的换取下载链接、流式下载、SHA-256 去重、落盘保存与元数据入库流程，并在处理完成后通过一条回复向发送者汇总每张图片的保存成功或重复结果。单张图片处理失败 MUST NOT 中断同一消息中其余图片的处理。图片处理完成后，消息 SHALL 继续流转至后续处理器。

#### Scenario: 单张群聊图片保存
- **WHEN** 群聊 @ 机器人发送一条包含 1 个图片段的 `richText` 消息
- **THEN** 系统提取该图片段的 `downloadCode`，完成下载、去重判断、落盘与元数据入库，并回复保存成功的文件名

#### Scenario: 多张群聊图片逐条保存并汇总回复
- **WHEN** 群聊 @ 机器人发送一条包含多个图片段的 `richText` 消息
- **THEN** 系统逐张保存全部非重复图片，且仅发送一条回复，在回复中列出每张图片对应的保存结果

#### Scenario: 多图中包含重复图片
- **WHEN** 一条 `richText` 消息的多个图片段中，部分图片的 SHA-256 已存在于索引且磁盘文件存在
- **THEN** 重复图片不重复落盘，其余图片正常保存，汇总回复中分别标明每张图片"已保存"或"已存在"

#### Scenario: 单张图片失败不阻断其余图片
- **WHEN** 一条 `richText` 消息中某张图片下载或保存失败，而其余图片正常
- **THEN** 系统继续处理并保存其余图片，汇总回复中标注失败图片的失败提示，且整个消息处理不抛出未捕获异常

#### Scenario: 无图片段的 richText 不触发保存
- **WHEN** 系统收到的 `richText` 消息中不存在任何含 `downloadCode` 的图片段
- **THEN** 系统不触发任何下载、去重或保存行为，该消息交由处理链中的后续处理器决定是否响应

#### Scenario: richText 图片处理后继续流转
- **WHEN** 系统完成 `richText` 消息中全部图片段的保存处理
- **THEN** 系统 SHALL 继续执行后续处理器，不终止处理链，以便同一消息的文本指令可被解析

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

### Requirement: Pipeline 流转模型
系统 SHALL 采用短路责任链模型：处理器返回 `True` 时终止处理链，返回 `False` 时继续流转至下一处理器。处理器默认返回 `False` 以允许消息流转。对于需要多个处理器协作的消息类型（如 `richText` 需同时完成图片保存与命令解析），各处理器 SHALL 独立解析原始消息数据，不通过中间字段传递结果，且不依赖处理器的装配顺序。

#### Scenario: richText 经多个处理器协作处理
- **WHEN** 一条 `richText` 消息进入处理链
- **THEN** 媒体处理器完成图片保存后返回 `False` 继续流转，命令处理器完成文本解析后返回 `False`（命中或未命中命令均返回 `False`），两者均独立完成各自职责

#### Scenario: 单媒体消息不终止处理链
- **WHEN** 一条 `picture`/`video`/`file` 消息进入处理链
- **THEN** 媒体处理器完成保存后返回 `False`，命令处理器运行但因非文本类型返回 `False`

### Requirement: 未命中文本兜底引导
当 `text` 或 `richText` 消息未命中任何文本指令、且消息不包含任何图片段时，系统 SHALL 向消息发送者回复一条使用引导，且引导 SHALL 采用三个正交维度组合而成：共情前缀、能力清单主体、结尾引导。各维度措辞 SHALL 固化在系统中并在每次触发时独立随机选取，不引入任何运行时配置项。共情前缀仅在归一化后存在实际文本时附加；归一化后为空字符串时前缀 MUST 为空，不得出现"听不懂/处理不了"等针对文本的表述。能力清单 SHALL 以条目形式列出：群聊 @ 机器人接收图片、单聊接收图片、单聊接收文件和视频、自动保存到服务器；其中文件和视频在任何措辞组合下 MUST 限定为单聊。对于包含图片段的消息，系统 MUST NOT 回复兜底引导，保存结果（成功、重复或失败）由媒体处理流程负责告知。兜底引导不改变命令处理结果，也不改变处理链的流转规则。

#### Scenario: 纯文本未命中指令触发组合引导
- **WHEN** 用户发送一条 `text` 消息，其内容在当前匹配器（子串或语义）下未命中任何指令
- **THEN** 系统回复由共情前缀、能力清单主体、结尾引导组合而成的引导；能力清单以条目形式列出四项能力，文件和视频限定为单聊

#### Scenario: 空文本不附加共情前缀
- **WHEN** 消息合并、trim 与空白归一化后为空字符串（仅 @ 机器人无输入，或群聊视频产生的空 `richText` 帧）
- **THEN** 系统直接以能力清单主体和结尾引导回复，回复中不含共情前缀，也不含任何"听不懂这句话"类表述

#### Scenario: 无图片段的 richText 未命中指令触发引导
- **WHEN** 一条 `richText` 消息不含任何图片段，合并归一化后的文本未命中指令
- **THEN** 系统按三维组合回复使用引导

#### Scenario: 含图片段的 richText 抑制引导
- **WHEN** 一条 `richText` 消息包含至少一个图片段，且文本部分未命中指令
- **THEN** 系统不回复兜底引导；用户仅收到媒体处理流程给出的保存结果回复（保存成功、重复提示或失败提示）

#### Scenario: 非文本类消息不触发引导
- **WHEN** 系统收到 `picture`、`video`、`file` 等非文本类消息
- **THEN** 系统不回复兜底引导，此类消息按媒体处理流程既有规则处理

### Requirement: 不支持消息类型的明确回复
当单聊收到系统不执行保存的消息类型（当前为语音 `audio`，以及任何未被识别的消息类型）时，系统 SHALL 向发送者回复一条明确说明暂不支持接收该类型消息的回复，不执行保存，也 MUST NOT 同时触发"未命中文本兜底引导"。回复措辞 SHALL 与兜底引导同样亲切自然，且固化在代码中、不引入配置项。群聊中此类消息的内容平台不投递，系统无法按类型分拣，不按本要求回复。

#### Scenario: 单聊语音明确回复不支持
- **WHEN** 用户在单聊发送一条语音消息（`msgtype=audio`）
- **THEN** 系统不保存该消息，回复一条"暂不支持接收语音消息"的明确提示，且不回复功能介绍式兜底引导

#### Scenario: 单聊未识别消息类型明确回复
- **WHEN** 单聊收到不属于系统已识别集合的消息类型
- **THEN** 系统回复"暂不支持接收该类型消息"的明确提示，不执行保存，不触发兜底引导

#### Scenario: 不支持提示与兜底引导不叠加
- **WHEN** 一条单聊消息因类型不支持被明确回复
- **THEN** 用户仅收到一条"不支持类型"回复，不会额外收到兜底引导
