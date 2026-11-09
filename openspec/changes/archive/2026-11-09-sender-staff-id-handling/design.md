# Design

## Context

见 [proposal.md](./proposal.md)。现有约束：

- `metadata_store.py` 用 `PRAGMA user_version` 严格等值校验，版本不符即抛错，无迁移链（`CURRENT_SCHEMA_VERSION = 1`）。
- `insert_record` / `async_insert_record` 在测试中大量以位置参数调用（`store.insert_record("u1", "a.jpg", path, "sha1", 1, "User 1")`）。
- 文件名唯一生成点 `generate_saved_filename`，其入参已命名为 `sender_staff_id`，且只被 `save_file` 调用。
- 回复的 @ 提及由 SDK 直接读取原始消息对象的 `sender_staff_id`，不经过文件名链路。

## Goals / Non-Goals

**Goals**

- 文件名后缀压缩到 4 字符，并去掉时间戳中的毫秒段，整体格式 `YYYYMMDD_HHMMSS_末4位ID.ext`。
- `sender_staff_id` 与 `sender_id` 两列各自单一语义，和消息体字段一一对应。
- 保持 `user_version = 1`，不写迁移代码。

**Non-Goals**

- 不改变统计口径（用户数仍按 `sender_id` 去重）。
- 不改变回复路由与 @ 提及逻辑。
- 不为旧库提供自动补列或迁移路径。

## Decisions

### 1. 截断发生在清洗之后，且在命名函数内

```python
clean = sanitize_sender_id(sender_staff_id)
suffix = f"_{clean[-4:]}" if clean else ""
time_str = ts.strftime("%Y%m%d_%H%M%S")
```

- 先清洗再截尾：反序会因尾部空白被 strip 掉而产生位数不足的后缀。
- 截断放在 `generate_saved_filename` 而不是 `sanitize_sender_id`：后者职责是"字符合法化"，与命名策略无关；且它是该函数唯一调用方，改动不影响其他逻辑。
- Python 切片 `[-4:]` 天然处理短 ID，无需分支。
- 去掉毫秒段：richText 多图按各自落盘时刻命名，天然跨秒；同秒撞名仅剩并发低概率，`_1`/`_2` 自增兜底已足够，3 位毫秒段对可读性的损失大于收益。

备选：在 `sanitize_sender_id` 里加 `max_length` 参数。否决，因为会引入一个只有单一取值的参数，属于为假想需求增加抽象。

### 2. 新增 `sender_staff_id TEXT`，可空，不写 `unknown`

- 保留原始值，不存清洗值、不存截断值：列是事实记录，文件名才是展示优化。
- 可空：`senderStaffId` 缺失时文件名已降级为无后缀，DB 侧保持 `NULL` 比伪造 `unknown` 更诚实，也便于后续 `WHERE sender_staff_id IS NOT NULL` 筛选。

### 3. `sender_id` 净化：`senderId -> unknown`

去掉 `senderStaffId` 兜底。理由：列注释与列名现在唯一的含义是"加密 senderId"，混入 staffId 会让同一列出现两种 ID 体系，破坏按列统计与后续 join 的前提。样本已证实 `senderId` 恒存在，净化不会造成实际数据损失。

### 4. 版本保持 1，新列并入 v1 建表语句

部署时删除旧库重建。备选：递增到 2 并写 `ALTER TABLE` 迁移。否决，因为：
- 用户明确部署时会删库，迁移代码永无执行机会。
- 现有 spec 已规定"系统 SHALL NOT 自动升级旧结构；旧库由部署时人工删除后重建"。
- 少一条永不测试的代码路径。

代价：同为版本 1 但缺少新列的库无法在启动时被识别（版本号相同），首次写入会报列不存在。已在 spec 中如实登记为部署前置条件。

### 5. `insert_record` 新参数追加在参数表末尾

```python
def insert_record(self, sender_id, original_filename, saved_path, sha256,
                  file_size=None, sender_nick=None, created_at=None,
                  media_type=None, sender_staff_id=None)
```

备选：插到 `sender_id` 之后紧邻。否决，会破坏约 20 处位置参数测试调用，收益仅是参数排列更好看。调用方（`message.py`）一律用关键字传参。

## Risks / Trade-offs

- [同版本旧库缺少新列，启动不报错、写入才报错] → 部署清单强制删除 `metadata.sqlite`；README/部署说明同步一句。本次改动明确未部署，实际风险为零。
- [末 4 位撞名 + 同秒撞名] → 4 位后缀空间约 1e4（数字）或 36^4（字母数字），配合秒级时间戳与同秒 `_1` 自增兜底，实际撞名概率可忽略；即便撞名也只影响文件名观感，DB 两列均存完整值，统计不受影响。
- [`senderId` 缺失时多个文件归入 `unknown`，用户数被低估] → 四类实测样本中该字段恒存在；若未来确认缺失，应按 `sender_staff_id` 另立统计口径，而不是恢复回退链。
- [截断值被误用于回复 @ 提及] → 回复走原始消息对象，物理上不经过命名函数；spec 已新增「三个消费位置互不替代」Scenario 兜住回归。

## Migration Plan

1. 代码上线前删除生产 `OUTPUT_DIR/metadata.sqlite`（部署脚本或手工）。
2. 启动服务，v1 建表语句直接建成含 `sender_staff_id` 的库。
3. 回滚策略：回退代码即可，但回退后旧代码向已含新列的库写入仍工作（多出的列不参与其 INSERT）；若需完全回退，删除库重建。

## 测试要点

- 命名：16 位数字取末 4 位、11 字符取末 4 位、3 字符原样、空值无后缀；文件名不含毫秒段。
- 存储：`sender_staff_id` 存完整值；`senderId` 缺失时 `sender_id = 'unknown'` 且 `sender_staff_id` 保留；`senderStaffId` 缺失时该列为 `NULL`。
- 回归：回复 `atUserIds` 仍是完整 `senderStaffId`。
