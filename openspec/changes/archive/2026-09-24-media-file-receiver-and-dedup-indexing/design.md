## Context

当前系统仅在 `app/main.py` 中注册了一个硬编码的 `CalcBotHandler`，无法应对文件传输与指令处理等多类型消息场景。用户希望能够稳定、异步地接收大体积多媒体文件并保存于 `OUTPUT_DIR`，同时基于本地 SQLite 索引与 SHA-256 哈希实现物理文件层面的精确防重，并支持运维人员归档文件后通过聊天指令完成索引数据清洗。

## Goals / Non-Goals

**Goals:**
- 基于职责链模式（Chain of Responsibility）设计可插拔的消息处理管道，解耦普通文本指令与多媒体文件处理。
- 全链路原生异步 I/O：使用 `httpx.AsyncClient` 进行下载流传输，边读边计算 SHA-256，杜绝大文件阻塞内存与事件循环。
- 设计 `OUTPUT_DIR/metadata.sqlite` 单表结构，执行“SHA-256 匹配 + 物理文件 `os.path.exists`”双重查重。
- “重建索引”异步维护：扫描表记录并比对磁盘文件，清理已归档文件的记录。
- 所有同步的 SDK 回复（如 `reply_text`）统一封装 `asyncio.to_thread` 投递至线程池。

**Non-Goals:**
- 不涉及文件的云端存储转存（如自动同步 OSS/S3），仅聚焦于本地文件系统的可靠写入与索引。
- 不引入外部数据库服务，严格使用轻量级本地 SQLite。

## Decisions

### 1. 消息处理器职责链设计
- **结构设计**：
  ```text
  [ChatbotMessage 入口]
           |
           v
  [PipelineHandler (ChatbotHandler 适配器)]
           |
           +---> 1. CommandHandler (检查是否为 "重建索引" 等文本命令)
           |        ├── 命中: 执行重建操作并回复
           |        └── 未命中: 传递给下一个处理器
           |
           +---> 2. MediaFileHandler (检查是否为 picture / video / file)
           |        ├── 命中: 流式下载 -> SHA256 查重 -> 落盘保存 -> 记入 SQLite
           |        └── 未命中: 传递给下一个处理器
           |
           +---> 3. DefaultFallbackHandler (兜底响应或忽略)
  ```
- **收益**：避免把所有业务逻辑堆叠在单一巨大的 `process()` 函数中，方便后续扩展更多业务指令。

### 2. 异步流式下载与 SHA-256 计算
- **策略**：
  1. 调用钉钉 OpenAPI `/v1.0/robot/messageFiles/download` 异步获取下载直链。
  2. 使用 `httpx.AsyncClient.stream("GET", url)` 以 64KB 为 chunk 流式拉取。
  3. 先写入临时文件 `OUTPUT_DIR/.tmp/xxx`，同时更新 `hashlib.sha256()`。
  4. 下载完毕后，根据 SHA-256 查询 SQLite：
     - 若已存在同哈希记录且磁盘对应文件确实存在：删除临时文件，通过 `asyncio.to_thread(self.reply_text, "文件已存在，请勿重复发送", msg)` 告知用户。
     - 若不存在（或虽有记录但磁盘原文件已不存在）：将临时文件重命名移动至 `OUTPUT_DIR/yyyy-MM-dd/[发送者]_时间戳.原扩展名`，并将记录插入 SQLite。

### 3. SQLite 元数据表结构与并发安全
- **表结构**：
  ```sql
  CREATE TABLE IF NOT EXISTS file_metadata (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sender_id TEXT NOT NULL,
      sender_nick TEXT,
      created_at TEXT NOT NULL,          -- yyyy-MM-dd HH:mm:ss
      original_filename TEXT NOT NULL,
      saved_path TEXT NOT NULL,          -- 相对或绝对存储路径
      sha256 TEXT NOT NULL,
      file_size INTEGER
  );
  CREATE INDEX IF NOT EXISTS idx_file_sha256 ON file_metadata(sha256);
  ```
- **异步安全**：将 SQLite 的读写与游标操作通过 `asyncio.to_thread` 封装，或使用 `aiosqlite` 异步上下文，保证数据库 I/O 不卡顿 asyncio 事件循环。

### 4. “重建索引”维护逻辑
- **流程**：
  1. 查询 `SELECT id, saved_path FROM file_metadata`。
  2. 遍历检查 `os.path.exists(saved_path)`。
  3. 收集所有物理文件已不存在的 `id` 列表。
  4. 执行 `DELETE FROM file_metadata WHERE id IN (...)`。
  5. 回复发送者：“索引重建完成，清理元数据 {cleaned_count} 条，现有有效索引 {remaining_count} 条。”

## Risks / Trade-offs

- **[Risk] 同一发送者在极短时间内上传多个同名文件造成文件名冲突**
  → **Mitigation**：文件名时间戳精确到毫秒或附加微秒/随机短字符串（如 `[发送者]_YYYYMMDDHHmmss_SSS.ext`），杜绝重名覆盖。
- **[Risk] 钉钉返回的文件名可能包含非法字符或路径遍历攻击（如 `../`）**
  → **Mitigation**：对 `original_filename` 提取扩展名前进行严格清洗，仅保留安全字符，防止路径穿越。
- **[Risk] 重建索引期间发生文件写入**
  → **Mitigation**：SQLite 开启 WAL 模式保证事务隔离性，删除操作通过单事务完成。
