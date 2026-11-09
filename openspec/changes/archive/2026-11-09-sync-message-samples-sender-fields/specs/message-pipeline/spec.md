# Spec Delta

## MODIFIED Requirements

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
- **THEN** 回调消息 `text.content` 为 `" hello"`（前导空格，`@机器人名` 已被平台移除），且 `isInAtList=true`、`atUsers` 包含机器人 `dingtalkId`，发送者三字段同样存在：
  ```json
  {
    "conversationType": "2",
    "msgtype": "text",
    "text": { "content": " hello" },
    "isInAtList": true,
    "atUsers": [{ "dingtalkId": "<chatbot_user_id>" }],
    "chatbotUserId": "<chatbot_user_id>",
    "conversationTitle": "<group_title>",
    "senderNick": "<nick>",
    "senderStaffId": "<staff_id>",
    "senderId": "<sender_id>"
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
- **WHEN** 群聊中用户先选两张图再 @ 机器人发送 "[图1] [图2] @机器人"（Android 端实测，5 段）
- **THEN** `content.richText` 为「图片段 + 换行段」交替、尾部为 @ 提及段，且携带完整发送者三字段：
  ```json
  {
    "conversationType": "2",
    "msgtype": "richText",
    "isInAtList": true,
    "atUsers": [{ "dingtalkId": "<chatbot_user_id>" }],
    "chatbotUserId": "<chatbot_user_id>",
    "conversationTitle": "<group_title>",
    "senderNick": "<nick>",
    "senderStaffId": "<staff_id>",
    "senderId": "<sender_id>",
    "content": {
      "richText": [
        { "type": "picture", "downloadCode": "<download_code>", "pictureDownloadCode": "<picture_download_code>" },
        { "text": "\n" },
        { "type": "picture", "downloadCode": "<download_code>", "pictureDownloadCode": "<picture_download_code>" },
        { "text": "\n" },
        { "text": "@机器人" }
      ]
    }
  }
  ```
  @ 提及在 `richText` 中始终以独立 text 段形式存在，位置不固定（可在段首或段尾，由用户发送消息时的编辑决定）。系统日志中出现的 `<img1>`、`<img2>` 是合并时生成的占位符（见「richText 文本语义合并与命令解析」），不属于平台原始负载。

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
- **THEN** 平台将多张图片拆分为多条独立的 `picture` 消息回调，每条消息仅含一张图片的 `downloadCode`，并携带发送者三字段：
  ```json
  {
    "conversationType": "1",
    "msgtype": "picture",
    "senderNick": "<nick>",
    "senderStaffId": "<staff_id>",
    "senderId": "<sender_id>",
    "content": {
      "downloadCode": "<download_code>",
      "pictureDownloadCode": "<picture_download_code>"
    }
  }
  ```
  单聊 `picture` 消息无 `atUsers`、无 `isInAtList` 字段。

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

#### Scenario: 发送者字段在实测消息中均存在
- **WHEN** 系统接收本次实测覆盖的四类消息：单聊 `text`、单聊 `picture`、群聊 `text`、群聊 `richText`
- **THEN** `senderNick`、`senderStaffId`、`senderId` 三个字段均存在，无缺失；实现 MUST NOT 假设任一字段必然存在，取值仍按 `${senderId} -> ${senderStaffId} -> unknown` 的回退链处理。

#### Scenario: 发送者字段取值形态与跨会话稳定性
- **WHEN** 系统解析同一发送者在单聊与群聊中发出的消息
- **THEN** 三个字段的取值形态为：`senderNick` 为中文昵称；`senderStaffId` 在企业内唯一，测试环境为短字母数字串（实测 11 字符，形如 `managerNNNN`），生产环境为 16 位数字；`senderId` 为 `$:LWCP_v1:$` 前缀的加密串（本次实测 43 字符：11 字符前缀 + 32 字符主体），长度 MUST NOT 写死。同一用户在同一环境下，跨单聊/群聊、跨 `text`/`picture`/`richText` 的 `senderId` 与 `senderStaffId` 取值相同，可直接用于用户维度的去重统计；文件名使用的 `senderStaffId` 与元数据入库使用的 `senderId` 是两个独立取值，互不替代。
