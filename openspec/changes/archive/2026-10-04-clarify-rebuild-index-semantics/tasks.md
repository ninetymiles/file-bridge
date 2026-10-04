# Tasks

## 1. 修订 file-indexing 规范措辞

- [x] 1.1 将"重建索引维护指令" Requirement 标题与正文改为准确描述"校验元数据记录与磁盘文件一致性并清理缺失记录"的语义，并显式补充"不扫描文件系统补录新文件、不更新已有记录、不校验文件内容"的边界说明。验证：`openspec/specs/file-indexing/spec.md` 中该 Requirement 不再使用"重建"暗示补录语义，且行为约束与 `MetadataStore.rebuild_index` 实现一致。
- [x] 1.2 同步修订"启动时自动重建索引" Requirement 中沿用"重建"的措辞（保留既有行为约束：SDK 连接前执行、INFO 日志、不发机器人通知、空库正常通过）。验证：该 Requirement 的 Scenario 判定结果不变，仅术语对齐。
- [x] 1.3 在规范中注明两点：(a) 回复文案（含清理数与剩余数）属展示层，规范只约束信息要素不锁定措辞；(b) 内部实现沿用 `rebuild_index` 命名。验证：spec.md 含对应说明文字。

## 2. 校验

- [x] 2.1 运行 `openspec validate clarify-rebuild-index-semantics` 通过。验证：命令退出码为 0。
