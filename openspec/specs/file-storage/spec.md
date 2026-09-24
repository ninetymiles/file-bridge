# file-storage Specification

## Purpose
定义接收到的多媒体与文件的异步下载与本地存储规范，包含按日期分目录归档及规范化文件命名规则。

## Requirements

### Requirement: 消息中的文件识别与异步流式下载
系统 SHALL 自动识别单聊与群聊中传输的图片（`picture`）、视频（`video`）以及普通文件（`file`），并使用原生异步 I/O 流式下载至临时缓冲区或直接计算哈希。

#### Scenario: 接收图片文件
- **WHEN** 用户在单聊或群聊中发送图片消息
- **THEN** 系统提取其 `downloadCode` 并通过异步 HTTP 客户端流式获取二进制数据

#### Scenario: 接收视频或常规文件
- **WHEN** 用户在单聊或群聊中发送视频或普通文件
- **THEN** 系统从消息负载中获取文件名与 `downloadCode`，并执行异步流式下载

### Requirement: 规范化目录结构与文件命名
系统 SHALL 将未重复的文件持久化保存在 `OUTPUT_DIR` 下对应的日期子目录中，并使用统一的文件命名格式。

#### Scenario: 目录与文件名生成
- **WHEN** 判定文件合法且非重复，需要落盘保存
- **THEN** 系统在 `OUTPUT_DIR` 下创建以发送日期命名的目录 `yyyy-MM-dd`，并将文件命名为 `[发送者]_时间戳.原扩展名` 保存于该目录中
