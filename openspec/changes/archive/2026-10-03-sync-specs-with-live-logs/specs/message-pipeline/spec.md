## MODIFIED Requirements

### Requirement: 平台消息投递范围适配
系统 SHALL 按钉钉平台的实际投递范围处理回调消息：单聊（`conversationType=1`）平台投递 `text`、`picture`、`video`、`file`、`audio` 与 `richText` 类型，其中系统保存 `picture`、`video`、`file` 与 `richText` 图片段，`audio` 不保存（按"不支持消息类型的明确回复"要求回复）；群聊（`conversationType=2`）投递 @ 机器人的 `text` 消息与 `richText` 消息，其中群聊图片以 `richText` 的图片段形式投递。群聊中 `file`、`video`、`audio` 的消息内容 MUST NOT 被假设为可获取（平台不投递内容）；其中群聊视频会额外产生一条仅含 @ 段与换行、不含任何图片段的 `richText` 帧，系统按空文本处理。单聊中发送视频时附带的文本以独立 `richText` 消息投递（与 `video` 消息分离，Android 端实测），不带文本时平台可能额外投递仅含换行段的空 `richText` 帧；此类不含图片段的纯文本 `richText` 归一化后按文本消息处理。系统 MUST NOT 在应用层对"消息是否发给机器人"做分拣——平台已保证群聊消息均来自 @ 机器人，所有到达回调入口的消息均直接进入处理链。

#### Scenario: 群聊图片以 richText 投递
- **WHEN** 群成员在群聊中 @ 机器人并发送图片
- **THEN** 系统收到的消息类型为 `richText`，图片二进制的 `downloadCode` 位于 `content.richText` 列表中 `type=picture` 的段落内，而非顶层 `picture` 消息

#### Scenario: 群聊文件、视频、语音不投递
- **WHEN** 群成员在群聊中 @ 机器人发送文件、视频或语音
- **THEN** 钉钉平台不向机器人投递该消息的内容与下载码，系统不执行保存；文件与视频的接收能力仅在单聊中可用（群聊视频的空帧行为见下一 Scenario）

#### Scenario: 群聊视频产生空 richText 帧
- **WHEN** 群成员在群聊中 @ 机器人发送一条视频（Android 端实测）
- **THEN** 系统额外收到一条 `richText` 消息，仅包含 @ 机器人的 text 段与一个换行 text 段，不含图片段；@ 段在帧中的位置由用户发送消息时的编辑决定、不固定（实测样本中位于段尾）；归一化后文本为空，系统按"未命中文本兜底引导"以空前缀直接回复能力清单

#### Scenario: 单聊视频附带文本独立投递
- **WHEN** 用户在单聊中发送视频时附带文本（Android 端实测）
- **THEN** 视频内容以 `video` 消息投递，附带文本以一条独立的纯文本 `richText` 消息投递（不含图片段）；两条消息各自独立进入处理链，文本经合并归一化后参与命令匹配

#### Scenario: 单聊视频产生空 richText 帧
- **WHEN** 用户在单聊中发送视频且不带文本（Android 端实测）
- **THEN** 平台可能额外投递一条仅含换行 text 段、不含图片段的 `richText` 帧；归一化后文本为空，系统按"未命中文本兜底引导"以空前缀直接回复能力清单

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
  @ 提及在 `richText` 中始终以独立 text 段形式存在，位置不固定（可在段首或段尾，由用户发送消息时的编辑决定）。

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

#### Scenario: 单聊 richText 纯文本消息结构
- **WHEN** 单聊收到不含图片段的 `richText` 消息（实测样本来自视频发送场景：附带文本或空文本帧）
- **THEN** `content.richText` 仅含 text 段，文本内容可能被拆分为多个换行段与内容段（无 @ 提及段）：
  ```json
  {
    "conversationType": "1",
    "msgtype": "richText",
    "content": {
      "richText": [
        { "text": "\n" },
        { "text": "\n" },
        { "text": "hello" }
      ]
    }
  }
  ```
  合并后文本为 `\n\nhello`，归一化后为 `hello`，按文本消息参与命令匹配。

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

#### Scenario: 单聊 video 消息结构
- **WHEN** 用户在单聊中发送一条视频（Android 端实测）
- **THEN** 回调消息 `msgtype` 为 `video`，`content` 包含 `downloadCode`、`duration`（字符串形式的秒数，如 `"6"`）与 `videoType`（如 `"mp4"`），不含 `fileName` 字段：
  ```json
  {
    "conversationType": "1",
    "msgtype": "video",
    "content": {
      "duration": "6",
      "videoType": "mp4",
      "downloadCode": "<download_code>"
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
