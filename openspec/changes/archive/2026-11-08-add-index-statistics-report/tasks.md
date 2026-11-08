# Tasks

## 1. 索引结构与 schema 版本校验

- [x] 1.1 在 `app/services/metadata_store.py` 中为 `file_metadata` 建表语句新增可空列 `media_type TEXT`，并验证 `tests/test_metadata_store.py::test_metadata_store_init` 通过且列存在于 `PRAGMA table_info`
- [x] 1.2 `init_db()` 在 `sqlite3.connect` 之前用 `os.path.exists` 判断库文件是否为新库：新库在同一 `BEGIN IMMEDIATE` / `COMMIT` 内建当前结构并写入 `PRAGMA user_version = 1`，不执行任何迁移
- [x] 1.3 库文件已存在时读取版本，仅接受等于 `CURRENT_SCHEMA_VERSION`（1）的值；版本为 0 或高于 1 时抛出包含库路径、发现版本与支持版本的显式异常并终止启动，不修改数据库
- [x] 1.4 不引入 v0 迁移与列探测逻辑，确认 `init_db()` 不包含 `ALTER TABLE` 或 `PRAGMA table_info` 分支
- [x] 1.5 新增测试覆盖：库文件不存在时创建并写入版本 1 且列存在；已存在版本 1 时正常启动；已存在版本 0（旧库或空文件）时拒绝启动且库未修改；已存在版本 2 时拒绝启动；模拟建库中断留下的空文件时拒绝并提示删除

## 2. 媒体类型入库

- [x] 2.1 `MetadataStore.insert_record` / `async_insert_record` 增加可选参数 `media_type` 并写入该列，验证既有未传该参数的调用仍可通过测试
- [x] 2.2 `MediaFileHandler` 入库时传入消息类型：`picture` / `video` / `file` 传 `msgtype`，`richText` 图片段固定传 `picture`，验证 `tests/test_media_file_handler.py` 中断言入库参数的用例通过
- [x] 2.3 在 `tests/test_media_file_handler.py` 新增用例覆盖三种顶层类型与 richText 图片段的入库媒体类型断言

## 3. 统计聚合查询

- [x] 3.1 在 `MetadataStore` 实现同步统计查询：总记录数、去重用户数、按 `media_type` 分类型计数、按 `date(created_at)` 的分日人数与份数、最近日期；另返回 `media_type IS NULL` 记录的 `saved_path` 列表
- [x] 3.2 实现异步包装（沿用 `asyncio.to_thread`），验证异步结果与同步结果一致
- [x] 3.3 新增 `tests/test_metadata_store.py` 统计用例：空库、单日多类型、多日多用户、媒体类型为空的记录混杂，断言各计数与最近日期正确

## 4. 报告渲染

- [x] 4.1 新增报告渲染纯函数模块：输入统计结果值对象，输出报告文本；类型回退扩展名集合作为代码常量
- [x] 4.2 实现三分支渲染：空索引空状态、单日单块（含人数与照片/视频/其他分项）、多日总量块 + 最近新增块，验证单日分支不出现重复总量描述
- [x] 4.3 新增渲染单元测试覆盖三个分支、`NULL` 记录按扩展名归类（图片/视频/未知扩展名）、报告文案包含人数与分项，并断言渲染不写库

## 5. 命令接入

- [x] 5.1 在 `app/services/command_matching/catalog.py` 新增 `INDEX_REPORT` 命令 id 与八个陈述式触发短语，并在 `__init__.py` 导出，验证子串匹配器命中全部短语
- [x] 5.2 在 `tests/test_command_matching.py` 新增用例：八个触发短语均命中 `INDEX_REPORT`，`统计一下有多少照片` 被疑问拦截不命中
- [x] 5.3 在 `app/main.py` 分发表注册 `INDEX_REPORT` 回调：记录 INFO 命令日志，调用统计查询与渲染后返回文本，验证 `tests/test_command_handler.py` 中命令分发用例通过
- [x] 5.4 新增端到端用例：构造含多日数据的索引后触发统计命令，断言回复文本包含总量与最近新增两段

## 6. 文档

- [x] 6.1 在 `docs/` 的指令说明中补充统计报告命令与触发短语，验证文档描述与命令目录一致
- [x] 6.2 在 `docs/` 的存储说明中补充 `media_type` 列与 schema 版本校验行为（版本 1、不匹配拒绝启动、部署需删除旧库），验证与 `openspec/specs/file-indexing/spec.md` 表述一致

## Workflow follow-up

- Archive the change after the project's review requirements are satisfied.
- Verify the archived result.
