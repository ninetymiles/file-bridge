# expand-command-phrases

## Why

当前命令目录仅注册 `rebuild_index` 一个命令，且只配置 4 条触发短语（重建索引 / 重新建立索引 / 重建文件索引 / rebuild index）。`rebuild_index` 的真实职责是**校验元数据记录与磁盘文件的一致性并清理缺失记录**（见 `clarify-rebuild-index-semantics`），用户表达该意图时常用"检查索引""同步索引""刷新索引"等说法，现有目录无法覆盖，导致命令漏召回。需要围绕该命令的真实语义扩充触发短语集合，使命令在口语化表达下仍能稳定命中。

## What Changes

- 围绕"校验/同步/清理"语义扩充 `rebuild_index` 的触发短语，覆盖三类常用说法：
  - 检查类：检查索引、校验索引、检查文件索引
  - 同步类：同步索引、同步文件索引
  - 刷新类：刷新索引、刷新文件索引、更新索引
- 沿用现有共用目录结构（子串匹配器与语义匹配器共用同一份短语集合），**不新增"语义专属短语"分组**，不修改匹配器架构。
- 扩充语义验收测试的正/负样本：为新增短语补充正样本，并补充状态询问类负样本（如"重新构建索引了吗""刷新索引完成了吗"）以拦截命令/查询边界误判。
- 受 `rebuild_index` 真实职责约束，**不纳入**"生成索引""重新生成索引"等暗示"补录新文件"语义的短语。
- 命令 id、命令回调、匹配阈值（0.8）、模型、归一化逻辑均保持不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `semantic-command`: 修改"命令目录与分发表" Requirement —— `rebuild_index` 命令的触发短语集合扩充；明确触发词的选取须与该命令"校验一致性并清理缺失记录"的职责语义一致，不引入暗示"生成/补录文件"语义的短语。匹配机制、阈值、分发与归一化行为不变。

## Impact

- **代码**：`app/services/command_matching/catalog.py`（扩充 `COMMAND_CATALOG[REBUILD_INDEX]` 短语）
- **测试**：`tests/test_semantic_command_smoke.py`（正/负样本扩充）、`tests/test_command_matching.py`（子串命中断言补充）
- **API / 依赖**：无
- **前置依赖**：`clarify-rebuild-index-semantics`（提供选词的职责基准）
- **风险**：新增短语抬高语义匹配的最高分，可能使状态询问类输入越过 0.8 阈值误命中——通过扩充负样本回归拦截，越线短语从目录剔除（数据层裁剪，不调阈值、不改算法）。
