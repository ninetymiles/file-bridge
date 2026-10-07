## Purpose

定义服务在生产默认 INFO 级别下的运行日志可观测性契约：启动时输出版本与生效配置，消息接收、媒体下载、机器人回复三类关键动作在 INFO 级别留下可追踪的事件记录，长连接生命周期只输出明确的连接/断开结论，同时将凭证与排障细节限制在 DEBUG，控制 INFO 噪音。

## ADDED Requirements

### Requirement: 启动版本与配置摘要
系统 SHALL 在每次启动完成日志初始化之后、建立钉钉连接之前，于 INFO 级别输出版本与运行配置摘要：版本号 SHALL 取自环境变量 `APP_VERSION`，当该变量缺失或为空时回退为 `dev`；配置摘要 SHALL 包含当前关联机器人的 `client_id`（明文）、生效日志级别、语义命令匹配开关状态（开启时表明语义模式、关闭时表明子串模式）、单聊通知目标开关与已配置的 staff id、群聊通知目标开关与已配置的 conversation id、文件输出目录。系统 MUST NOT 在任何日志中输出 `client_secret` 或访问令牌。

#### Scenario: 配置了 APP_VERSION 时显示注入版本
- **WHEN** 容器启动时环境变量 `APP_VERSION` 已设置为非空值（如 CI 从 git tag 注入的版本号）
- **THEN** 连接建立之前的版本行显示该值（如 `File Bridge starting: version=1.2.0`）

#### Scenario: 未配置 APP_VERSION 时回退 dev
- **WHEN** 本地运行或构建镜像时未注入 `APP_VERSION`（变量缺失或为空串）
- **THEN** 版本行显示 `dev`，启动不因此失败

#### Scenario: 默认配置启动时输出配置行
- **WHEN** 应用以任意配置启动
- **THEN** 连接建立之前出现配置行，可读出 client_id、日志级别、语义匹配模式、两类通知目标的开关状态及输出目录

#### Scenario: 通知目标部分配置时区分开关状态
- **WHEN** 仅配置了群聊通知目标、未配置单聊目标
- **THEN** 配置行中群聊目标显示为开启并附带 conversation id，单聊目标显示为关闭，不产生误导性的 id 输出

#### Scenario: 密钥不进入启动日志
- **WHEN** 环境中配置了 `CLIENT_SECRET`
- **THEN** 启动摘要与全部启动日志中均不出现该密钥内容

### Requirement: 接收消息正文在 INFO 级别可见
系统在每条消息的接收摘要 INFO 日志中 SHALL 携带可读的消息正文：`text` 消息附带文本正文；`richText` 消息附带按段合并后的单一文本，其中图片段 SHALL 以序号占位符（`<img1>`、`<img2>` …）表示，纯 @ 段不进入合并文本；当 richText 不含任何文本段时，正文 SHALL 仅由图片占位符构成。不携带文本内容的消息类型（如 picture、file、video、audio）MUST NOT 虚构正文字段。

#### Scenario: 文本消息正文出现在 INFO 接收日志
- **WHEN** 收到内容为"重建索引"的 text 消息
- **THEN** INFO 接收日志中包含发送者、消息类型与正文"重建索引"，无需开启 DEBUG 即可读到

#### Scenario: richText 图文混合时正文带图片占位符
- **WHEN** 收到含一个 @ 段、文字"重建索引 "和一张图片的 richText 消息
- **THEN** INFO 接收日志中的正文为图片占位符与文字合并后的文本（图片渲染为 `<img1>`、@ 段被剔除），同时保留段数统计

#### Scenario: richText 仅含图片时正文为占位符
- **WHEN** 收到不含任何文本段、仅含一张图片的 richText 消息
- **THEN** INFO 接收日志中的正文为 `<img1>`

#### Scenario: 非文本类型不虚构正文
- **WHEN** 收到 picture、file、video 或 audio 消息
- **THEN** INFO 接收日志包含发送者、类型及既有文件名等元数据，但不出现 content 正文字段

### Requirement: 媒体下载关键事件日志
对于每条进入下载流程的媒体（图片、视频、文件及 richText 中的每个图片段），系统 SHALL 在发起下载前输出一条 INFO 日志，包含消息类型与原始文件名；下载完成并保存成功后 SHALL 保持既有 INFO 成功日志。每个媒体文件在一次处理中 SHALL 仅产生一条下载开始日志。

#### Scenario: 冷盘等待期间存在下载开始标记
- **WHEN** 媒体消息进入下载阶段且磁盘唤醒导致后续操作长时间阻塞
- **THEN** 阻塞发生前已输出下载开始 INFO，排障时可据其确认消息已被接收并进入下载流程

#### Scenario: richText 多图逐张记录
- **WHEN** 一条 richText 消息含两张图片
- **THEN** 处理过程中依次出现两条下载开始日志，与最终的保存结果一一对应

### Requirement: 机器人回复内容在 INFO 级别可见
系统 SHALL 在每一条回复实际发出之后于 INFO 级别记录回复目标（单聊发送者或群聊会话）与完整回复文本；该记录 SHALL 覆盖全部回复出口，包括处理链裁决后的最终回复、存储唤醒提示、存储不可用提示、不支持类型提示。回复发送失败时系统 SHALL 输出 WARNING 级别日志指明该回复未送达。日志记录 MUST NOT 早于 DingTalk 发送动作，以避免冷盘期间本地日志 I/O 阻塞事件循环、延后面向用户的提示。

#### Scenario: 最终回复内容可见
- **WHEN** 一条文件消息保存成功并回复用户
- **THEN** INFO 日志中先出现接收与下载事件，DingTalk 发送完成后出现一条包含回复目标与"文件接收成功"完整文本的回复日志

#### Scenario: 存储唤醒提示发送可见
- **WHEN** 冷盘导致入口预热超过 3 秒
- **THEN** 唤醒提示的 DingTalk 发送先于本地 INFO 日志记录；该提示的完整文本在 INFO 日志可见，无需依赖 DEBUG 即可确认提示已发送

#### Scenario: 回复发送失败有明确告警
- **WHEN** 回复 HTTP 发送失败
- **THEN** 出现 WARNING 日志指示该回复发送失败，并可关联到对应回复文本

### Requirement: 存储预热先于消息处理链所有 INFO 日志
系统 SHALL 保证每条消息处理链中，存储预热（`ensure_storage_ready`）的探针启动与唤醒定时器注册发生在任何可能触发本地磁盘 I/O 的 INFO 日志之前。具体而言：接收摘要 INFO、下载开始 INFO、回复 INFO 均 MUST NOT 先于存储预热完成（唤醒提示回复除外，其在预热超时回调内发出，且发送动作先于本地日志）。此不变量旨在确保冷盘场景下唤醒定时器已注册且探针已开始唤醒磁盘，随后的 INFO 日志写入落在热盘窗口期，不因日志 I/O 阻塞事件循环而抵消预热提示的时效性。

#### Scenario: 接收摘要日志发生在预热之后
- **WHEN** 任意消息进入处理链
- **THEN** `ensure_storage_ready` 已被调用且探针已启动之后，才输出接收摘要 INFO 日志；若磁盘需要唤醒，唤醒提示的 DingTalk 发送先于该接收摘要日志

#### Scenario: 冷盘时唤醒定时器先于所有 INFO 日志注册
- **WHEN** 磁盘处于冷盘状态，消息进入处理链
- **THEN** 3 秒唤醒定时器在第一条 INFO 日志输出之前已完成注册，确保即使后续日志写入触发磁盘 I/O，唤醒提示仍能在 3 秒内送达用户

#### Scenario: 新增消息链 INFO 日志不得早于预热
- **WHEN** 未来在消息处理链中新增任何 INFO 级别日志输出
- **THEN** 该日志输出点 MUST 位于 `ensure_storage_ready` 调用之后；若该日志属于唤醒提示本身，则其 DingTalk 发送 MUST 先于该日志记录

### Requirement: 长连接生命周期结论日志
系统 SHALL 在 INFO 级别只输出钉钉长连接的生命周期结论：连接建立成功时输出一条明确的已连接日志；收到服务端 disconnect 系统消息而断开时输出一条明确的已断开日志，日志内容 SHALL 表明断开原因是收到 disconnect 消息。连接地址、endpoint 票据、disconnect 原始报文等过程细节 MUST NOT 在 INFO 级别输出。

#### Scenario: 重连成功输出结论行
- **WHEN** 长连接（含断线重连）建立成功
- **THEN** INFO 日志出现一条已连接结论，不包含 endpoint 字典、ticket 或连接 URL

#### Scenario: 服务端断开输出结论行
- **WHEN** 收到钉钉服务端的 disconnect 系统消息（如持久连接超时）
- **THEN** INFO 日志出现一条已断开结论并表明原因为收到 disconnect 消息，原始 disconnect JSON 报文不在 INFO 输出

#### Scenario: 过程细节仅在 DEBUG 可见
- **WHEN** 日志级别为 INFO
- **THEN** 打开连接的 URL、endpoint 详情均不出现；级别为 DEBUG 时这些过程信息仍可用于排障

### Requirement: INFO 噪音与凭证信息边界
系统 SHALL 抑制第三方 HTTP 客户端在 INFO 级别对每次请求输出的请求行，使其默认运行（INFO）下不产生逐请求日志；downloadCode、临时下载 URL（含签名参数）、访问令牌、回调报文头与原始 payload 等凭证或排障细节 MUST NOT 在 INFO 级别出现，SHALL 仅在 DEBUG 级别输出。

#### Scenario: 默认运行无逐请求 HTTP 日志
- **WHEN** 系统以默认 INFO 级别处理一条媒体消息
- **THEN** 日志中不出现第三方 HTTP 客户端的请求行（含带签名参数的 OSS URL），应用自身的下载开始与保存成功日志正常可见

#### Scenario: 凭证细节仅 DEBUG 可见
- **WHEN** 系统以 INFO 级别处理媒体消息
- **THEN** INFO 日志中不出现 downloadCode、临时下载 URL 与访问令牌；切换到 DEBUG 后这些信息仍按既有排障日志输出
