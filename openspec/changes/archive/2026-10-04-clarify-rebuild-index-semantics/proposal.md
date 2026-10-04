# clarify-rebuild-index-semantics

## Why

`file-indexing` 规范把磁盘一致性校验指令命名为"重建索引"，但源码实现（`MetadataStore.rebuild_index`）只做单向校验：遍历元数据表、删除磁盘文件已缺失的记录，**不扫描文件系统、不补录新文件、不更新已有记录、不校验文件内容**。"重建"一词暗示了实现中完全缺失的语义，误导后续维护者与意图词扩充决策（例如把"生成索引""重新生成索引"误当作合法触发词）。本变更依据源码实现重新梳理该指令的职责，使规范措辞与真实行为对齐。

## What Changes

- 重写 `file-indexing` 规范中"重建索引维护指令" Requirement：标题与措辞改为准确描述"校验元数据记录与磁盘文件的一致性并清理缺失记录"的语义，并显式声明"不扫描文件系统补录新文件"的边界。
- 同步修订"启动时自动重建索引" Requirement 中沿用"重建"措辞的描述，行为约束保持不变。
- 明确该指令的回复文案（含清理数与剩余数）属于展示层，规范只约束行为与信息要素，不锁定具体措辞。
- 规范中注明内部实现沿用 `rebuild_index` 命名，避免因方法名与规范术语不一致产生歧义。
- **本次不修改任何代码**；命令 id（`REBUILD_INDEX`）、方法名、触发词集合、匹配机制、回复文案的行为均保持不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 —— 本次为纯文档对齐，无 spec 级行为变化，已设置 `skip_specs: true`）

> 说明：本变更仅修订 `openspec/specs/file-indexing/spec.md` 的**描述性措辞**（Requirement 标题、术语、显式边界说明），不改变任何 Requirement 的行为约束或 Scenario 的判定结果。规范的"行为契约"与源码实现本就一致，只是术语不准确，因此不产生 spec delta。

## Impact

- **文档**：`openspec/specs/file-indexing/spec.md`（措辞修订，行为不变）
- **代码**：无
- **API / 依赖 / 系统**：无
- **后续**：为 `expand-command-phrases` 变更提供准确的职责基准——意图词扩充应围绕"校验/同步/清理"语义选取，而非"重建/生成"语义。
