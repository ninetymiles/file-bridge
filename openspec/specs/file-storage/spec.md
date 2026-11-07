# file-storage Specification

## Purpose
定义接收到的多媒体与文件的异步下载与本地存储规范，包含 `OUTPUT_DIR` 根目录落盘及规范化文件命名规则。

## Requirements

### Requirement: 消息中的文件识别与异步流式下载
系统 SHALL 自动识别平台实际投递的媒体消息，并使用原生异步 I/O 流式下载至临时缓冲区或直接计算哈希。可处理的媒体来源包括：单聊中的图片（`picture`）、视频（`video`）、普通文件（`file`），以及单聊与群聊中 `richText` 消息里带 `downloadCode` 的图片段。文件名与扩展名的获取规则按消息类型区分：`picture` 与 `richText` 图片段的负载中不含 `fileName` 字段，系统 SHALL 直接使用缺省文件名（`picture.png`、`picture_N.png`）与缺省扩展名（`.png`）；`file` 消息的负载中包含 `fileName` 字段，系统 SHALL 从中提取原始文件名与扩展名；`video` 消息若负载中无 `fileName`，系统 SHALL 使用缺省扩展名（`.mp4`）。

#### Scenario: 接收图片文件
- **WHEN** 用户在单聊中发送 `picture` 类型的图片消息
- **THEN** 系统提取其 `downloadCode` 并通过异步 HTTP 客户端流式获取二进制数据，使用缺省文件名 `picture.png` 与扩展名 `.png` 落盘

#### Scenario: 接收视频或常规文件
- **WHEN** 用户在"人与机器人"单聊中发送视频（`video`）或普通文件（`file`）
- **THEN** 系统从消息负载中获取 `downloadCode`；`file` 类型从 `fileName` 字段提取原始文件名与扩展名，`video` 类型在无 `fileName` 时使用缺省扩展名 `.mp4`，并执行异步流式下载

#### Scenario: 接收 richText 中的图片
- **WHEN** 用户在单聊或群聊中发送包含一个或多个图片段的 `richText` 消息
- **THEN** 系统从 `content.richText` 列表中逐个提取图片段的 `downloadCode`，逐张执行异步流式下载，使用缺省文件名 `picture_1.png`、`picture_2.png`……与扩展名 `.png` 落盘

#### Scenario: 群聊文件与视频平台不投递
- **WHEN** 群成员在群聊中 @ 机器人发送文件（`file`）或视频（`video`）
- **THEN** 钉钉平台不投递该消息；文件与视频的下载能力仅在单聊中提供，系统不假设能收到群聊 `file`/`video` 回调

### Requirement: 规范化目录结构与文件命名
系统 SHALL 将未重复的文件直接持久化保存在 `OUTPUT_DIR` 根目录，不创建按日期划分的子目录，并使用统一的文件命名格式 `时间戳.扩展名` 或 `时间戳_senderStaffId.扩展名`。

#### Scenario: 目录与文件名生成
- **WHEN** 判定文件合法且非重复，需要落盘保存
- **THEN** 系统将文件直接保存到 `OUTPUT_DIR` 根目录，不创建 `yyyy-MM-dd` 之类的日期子目录，文件名为 `时间戳_senderStaffId.原扩展名`，时间戳精度为毫秒（`YYYYMMDD_HHMMSS_fff`）

#### Scenario: senderStaffId 缺失时降级命名
- **WHEN** 消息的原始字段中不存在 `senderStaffId`，或该值清洗后为空
- **THEN** 文件名降级为 `时间戳.原扩展名`，不写入 `unknown` 等占位符

#### Scenario: 同一毫秒内撞名
- **WHEN** 目标文件名在 `OUTPUT_DIR` 中已存在
- **THEN** 系统在扩展名前追加 `_1`、`_2` 等自增后缀保存，不覆盖已有文件

#### Scenario: richText 多图各自时间戳
- **WHEN** 单条 richText 消息包含多张图片
- **THEN** 每张图片按各自落盘时刻生成时间戳，文件名互不相同
