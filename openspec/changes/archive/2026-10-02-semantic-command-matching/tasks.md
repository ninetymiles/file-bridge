## 1. 依赖与配置

- [x] 1.1 添加主依赖：`uv add fastembed`，验证 `uv run python -c "import fastembed, onnxruntime, numpy"` 成功、onnxruntime 为支持 cp314 的版本，且 `uv sync --no-dev`（镜像构建命令）包含该依赖
- [x] 1.2 在 `.env.example` 增加 `SEMANTIC_COMMAND_ENABLED=false`（附注释说明 true/1 启用语义匹配、开启首启需模型文件可获取），验证未设置该变量时应用现状行为不变

## 2. 匹配机制核心实现

- [x] 2.1 新建 `app/services/command_matching/` 包：`base.py` 定义 `BaseCommandMatcher` 抽象基类（async `match(text)->id|None`）与共享的 `normalize_command_text()`（正则去 `<imgN>`、折叠 strip 空白）；`catalog.py` 定义 `COMMAND_CATALOG`（首期仅 `rebuild_index`，含多条短语），验证目录可被两个实现共同导入消费
- [x] 2.2 `substring.py` 实现 `SubstringCommandMatcher`（仅用标准库，按目录声明顺序做短语包含判定返回 id），验证对 `重建索引`、` 重建索引 `、`请重建索引谢谢` 均命中、对无关文本不命中
- [x] 2.3 `semantic.py` 以普通顶层导入 `import fastembed`/`numpy`，实现 `FastEmbedEmbedder`（构造时加载模型；同步 `embed(list[str])` 返回 numpy 数组）与 `SemanticCommandMatcher`（模型名/阈值 0.8 常量；短语启动时批量 embed 存矩阵；输入经 `asyncio.to_thread` 推理；点积取跨短语最大分；阈值门控）。实施变更：fastembed 0.8.1 注册表无 multilingual-e5-small，经确认改用 `BAAI/bge-small-zh-v1.5`（512 维、无 E5 前缀约定，短语/输入均原文 embed）；维度与高/低分由 semantic smoke（test_embedding_dimension 及 20 条样本）验证，未使用临时脚本
- [x] 2.4 `__init__.py` 实现装配工厂 `build_command_matcher()`：顶层只导入 base/catalog/substring；读 `SEMANTIC_COMMAND_ENABLED`（true/1 大小写不敏感为真），默认返回子串匹配器，开启分支才 `from .semantic import ...` 构造语义匹配器（构造失败异常上抛，不回退）；两种路径均以 INFO 打印生效匹配器类型（语义含模型名），验证日志文案与 design 决策 3 一致

## 3. 处理器改造与装配

- [x] 3.1 改造 `app/handlers/message.py` 的 `CommandHandler`：构造参数改为 `matcher` 与 `dispatch_table`；保留 text/richText 文本提取，调用 `base.normalize_command_text()` 归一化，空文本直接不处理；执行段替换为按 id `await dispatch_table[command_id](message, raw_data, pipeline)`，验证 handler 内无具体命令知识
- [x] 3.2 修改 `app/main.py`：`create_pipeline` 增加 matcher 注入参数，并在其内部基于 `metadata_store` 构建默认分发表（`rebuild_index` 闭包，回复文案与现状逐字一致）；`main()` 启动区调用 `build_command_matcher()` 选出 matcher 传入（失败即终止），验证默认开关下启动日志输出 substring 且 `uv run python -c "from app.main import create_pipeline"` 可导入

## 4. 测试

- [x] 4.1 新增 `tests/test_command_matching.py` 子串匹配器单测：包含命中、不命中、多命令按目录顺序消歧；语义匹配器单测（fake embedder 可控向量）：阈值上门控、阈值下 None、跨短语取最大、query/passage 前缀拼接，验证该文件测试通过且不导入 fastembed
- [x] 4.2 新增装配工厂单测：monkeypatch 环境变量覆盖未设置/false/true/TRUE/1，断言默认与假值得到子串匹配器、真值路径桩掉语义构造器后得到语义匹配器且日志含 substring/semantic；令桩构造器抛错时异常向上传播且不回退为子串；断言默认路径装配后 `fastembed` 未进入 `sys.modules`，验证测试通过
- [x] 4.3 改写 `tests/test_command_handler.py`：注入 fake matcher（固定 id / None），验证命中分发执行并回复、未命中不执行、空文本/纯占位符不调用 matcher；保留 `_merge_rich_text` 全部既有测试，验证该文件测试通过
- [x] 4.4 修改 `tests/test_integration.py` 仅做装配接线：`create_pipeline(...)` 调用改为经参数注入真实 `SubstringCommandMatcher`（分发表由 create_pipeline 内建，无需测试构造）；文件不加 marker、继续留在默认集；5 步业务流程与全部断言（文件保存/去重/重建索引/richText 图文混合）及 MockTransport、MagicMock、reply_text 捕获均保持不变，验证该用例在默认 `uv run pytest` 中通过且全程不导入 fastembed
- [x] 4.5 在 `pyproject.toml` 注册 `general` 与 `semantic` 两个 marker，配置 `addopts = "-m general"`（使裸 `uv run pytest` 默认只跑通用集）；新建/更新 `tests/conftest.py`，用 `pytest_collection_modifyitems` 钩子将不含已登记专项 marker（`SPECIAL_MARKERS = {"semantic"}`）的测试自动标记为 general（既有测试无需逐个手贴），验证裸 `uv run pytest` 收集全部既有测试与新单元/组合测试但不收集 smoke、`pytest -m semantic` 只收集 smoke、`pytest -m ""` 收集全部
- [x] 4.6 新增 `tests/test_semantic_command_smoke.py`（标 `semantic`）：测试内直接构造真 `FastEmbedEmbedder`/`SemanticCommandMatcher`（不经工厂、不设置 SEMANTIC_COMMAND_ENABLED），内置 10 正例 10 负例固定样本，断言正例命中 ≥9/10、负例误命中 ≤1/10；模型不可用时直接 fail，验证 `uv run pytest -m semantic` 按通过线运行
- [x] 4.7 若 4.6 未达通过线，仅调整阈值、passage 短语表或样本集（样本须为真实说法）后重跑 `-m semantic` 直至达标，验证最终正/负例命中率满足通过线（实际：0.8 阈值首次运行即 10/10 正例、1/10 负例误中——"索引重建完成了吗"0.854，处于允许线内，未做调参）

## 5. 收尾验证

- [x] 5.1 运行 `uv run pytest`（CI 同命令）全量通过（99 passed、3 smoke deselected）、含原 integration 组合测试且不加载模型；本地运行 `uv run pytest -m semantic`（模型已缓存，HF_HUB_OFFLINE=1）达标（3 passed）；置 `SEMANTIC_COMMAND_ENABLED=true` 经工厂验证日志输出 `semantic (model=BAAI/bge-small-zh-v1.5, threshold=0.80)`（完整应用启动需钉钉凭证）；`openspec validate semantic-command-matching --strict` 通过
- [x] 5.2 更新 TODO.md：标注"支持语义化功能调用"机制部分已完成（默认子串、开关启用语义）；新增后续规划条目"手工管理本地 embedding 模型（裸 onnxruntime + tokenizers，去除 fastembed 下载链路）"，验证条目状态与实际一致
