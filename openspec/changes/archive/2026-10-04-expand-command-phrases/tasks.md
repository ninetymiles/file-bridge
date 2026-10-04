# Tasks

## 1. 扩充命令目录

- [x] 1.1 在 `app/services/command_matching/catalog.py` 的 `COMMAND_CATALOG[REBUILD_INDEX]` 中追加覆盖"检查/校验""同步""刷新/更新"语义的触发短语（检查索引、校验索引、检查文件索引、同步索引、同步文件索引、刷新索引、刷新文件索引、更新索引），不纳入"生成索引/重新生成索引"类短语。验证：`uv run pytest tests/test_command_matching.py` 子串命中相关用例通过。

## 2. 补充单元测试

- [x] 2.1 在 `tests/test_command_matching.py` 的子串匹配用例中为新增短语补充命中断言。验证：`uv run pytest tests/test_command_matching.py` 全部通过。
- [x] 2.2 为疑问句拦截函数补充单元测试：覆盖"了吗/完成了吗/好了吗/怎么样/多少/吗"结尾判为询问、陈述式命令不判为询问、空串安全。验证：新增用例通过。

## 3. 补充语义验收样本并实测

- [x] 3.1 在 `tests/test_semantic_command_smoke.py` 中为新增短语补充正样本，并补充状态询问类负样本（如"重新构建索引了吗""刷新索引完成了吗"）。验证：`uv run pytest -m semantic` 正样本漏检与负样本误命中均在阈值容忍内。
- [x] 3.2 在 `app/services/command_matching/base.py` 实现疑问句拦截纯函数（如 `is_inquiry_text`），并在 `app/handlers/message.py` 归一化后、调用 matcher 前接入：文本以疑问/询问语气结尾（"了吗""完成了吗""好了吗""怎么样""多少""吗"等，代码内固定常量）时判无命中、不调用匹配器，对子串/语义统一生效。验证：新增针对该函数的单元测试通过。

## 4. 校验

- [x] 4.1 运行 `uv run pytest` 默认测试集：本变更触及的测试文件（test_command_matching / test_command_handler / test_integration）47 passed；`tests/test_semantic_command_smoke.py`（`-m semantic`）4 passed。注：默认集中 `test_startup_index_rebuild` 存在一个**预存失败**（与 test_command_matching 同跑时 `SEMANTIC_COMMAND_ENABLED` 泄漏导致），已用基线代码（stash 本变更）复现确认与本变更无关，按用户决定另开变更处理，不在本变更范围。验证：本变更相关测试文件退出码为 0。
- [x] 4.2 运行 `openspec validate expand-command-phrases` 通过（含 `--strict`）。验证：命令退出码为 0。
