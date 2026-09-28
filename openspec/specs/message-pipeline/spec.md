# message-pipeline Specification

## Purpose

定义钉钉回调消息进入机器人后的统一接收入口规范，涵盖平台消息投递范围适配、平台消息结构约定、`richText` 图片段提取处理、`richText` 文本语义合并与命令解析、pipeline 流转模型，保障群聊 @ 机器人与单聊场景获得一致的消息处理体验。

以下消息结构均来自线上实测（已脱敏），作为后续设计与实现的参考基准。

## Requirements

### Requirement: 平台消息投递范围适配
系统 SHALL 按钉钉平台的实际投递范围处理回调消息：单聊（`conversationType=1`）处理 `text`、`picture`、`video`、`file` 与 `richText` 类型；群聊（`conversationType=2`）仅处理 @ 机器人的 `text` 消息与 `richText` 消息，其中群聊图片以 `richText` 的图片段形式投递。系统 MUST NOT 假设群聊中会收到 `file`、`video`、`audio` 消息（平台不投递），也 MUST NOT 在应用层对"消息是否发给机器人"做分拣——平台已保证群聊仅投递 @ 机器人的消息，所有到达回调入口的消息均直接进入处理链。

#### Scenario: 群聊图片以 richText 投递
- **WHEN** 群成员在群聊中 @ 机器人并发送图片
- **THEN** 系统收到的消息类型为 `richText`，图片二进制的 `downloadCode` 位于 `content.richText` 列表中 `type=picture` 的段落内，而非顶层 `picture` 消息

#### Scenario: 群聊文件、视频、语音不投递
- **WHEN** 群成员在群聊中 @ 机器人发送文件、视频或语音
- **THEN** 钉钉平台不向机器人投递该消息，系统不会产生任何回调、保存或回复行为；文件与视频的接收能力仅在单聊中可用

#### Scenario: 不对已投递消息做 @ 分拣
- **WHEN** 任意群聊回调消息到达处理入口
- **THEN** 系统直接进入处理链，不以 `isInAtList` 字段或 @ 列表作为"是否处理该消息"的判断门槛

#### Scenario: 不含可处理内容的消息正常 ACK
- **WHEN** 系统收到不含可识别文本指令且不含图片段的消息（如无图片段的 `richText`）
- **THEN** 系统正常确认回调，不触发文件保存流程，且不因此报错或重连

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
对于 `richText` 消息，系统 SHALL 将 `content.richText` 列表中的 text 段与图片段合并为单一语义文本字符串：text 段按序拼接（其中匹配 `^@\S+$` 的独立 @ 提及段被移除），图片段替换为 `<imgN>` 占位符（N 为图片序号，从 1 开始）。合并后的文本 SHALL 经过与 `text` 类型消息一致的命令匹配逻辑，命中时执行对应命令。合并逻辑仅服务于命令解析，不修改原始消息数据。

#### Scenario: richText 文本合并并触发命令
- **WHEN** 群聊收到 `richText` 消息，其 segments 为 `[@FileBridge, 重建索引, \n, pic1]`
- **THEN** 合并后的文本为 `重建索引\n<img1>`，命令"重建索引"被匹配并执行

#### Scenario: @ 提及在段尾时仍被正确剥离
- **WHEN** 群聊收到 `richText` 消息，其 segments 为 `[pic1, \n, @FileBridge]`
- **THEN** 合并后的文本为 `<img1>\n`，@ 提及被移除，不影响后续解析

#### Scenario: 单聊 richText 无 @ 提及
- **WHEN** 单聊收到 `richText` 消息，其 segments 为 `[pic1, \n, pic2]`
- **THEN** 合并后的文本为 `<img1>\n<img2>`，无 @ 提及需剥离

#### Scenario: 合并文本用于命令匹配
- **WHEN** `richText` 合并后的文本包含已知命令（如"重建索引"）
- **THEN** 系统执行该命令并回复结果；若不包含任何已知命令，则不执行命令

### Requirement: Pipeline 流转模型
系统 SHALL 采用短路责任链模型：处理器返回 `True` 时终止处理链，返回 `False` 时继续流转至下一处理器。处理器默认返回 `False` 以允许消息流转。对于需要多个处理器协作的消息类型（如 `richText` 需同时完成图片保存与命令解析），各处理器 SHALL 独立解析原始消息数据，不通过中间字段传递结果，且不依赖处理器的装配顺序。

#### Scenario: richText 经多个处理器协作处理
- **WHEN** 一条 `richText` 消息进入处理链
- **THEN** 媒体处理器完成图片保存后返回 `False` 继续流转，命令处理器完成文本解析后返回 `False`（命中或未命中命令均返回 `False`），两者均独立完成各自职责

#### Scenario: 单媒体消息不终止处理链
- **WHEN** 一条 `picture`/`video`/`file` 消息进入处理链
- **THEN** 媒体处理器完成保存后返回 `False`，命令处理器运行但因非文本类型返回 `False`
