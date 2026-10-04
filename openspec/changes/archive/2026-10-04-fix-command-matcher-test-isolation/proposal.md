# fix-command-matcher-test-isolation

## Why

默认测试集在多文件同跑时存在一个稳定复现的失败：`tests/test_startup_index_rebuild.py::test_startup_index_rebuild_logs_counts` 与 `tests/test_command_matching.py` 一起运行即报 `AttributeError: '_StubTextEmbedding' object has no attribute 'embed'`，但该测试单独运行通过。此问题在本次 `expand-command-phrases` 实施期间被发现，并用基线代码（stash 掉当次全部改动）复现，确认是**既有的测试隔离缺陷**，与扩短语/疑问句拦截改动无关。本提案先记录已查明的完整事实链与候选修复方向，具体方案待后续规划，不在本次定论或实施。

## 现象与复现

- 复现（失败）：`uv run pytest tests/test_command_matching.py tests/test_startup_index_rebuild.py -q` → `1 failed`，错误为 `_StubTextEmbedding` 缺少 `embed`。
- 对照（通过）：`uv run pytest tests/test_startup_index_rebuild.py -q` → `1 passed`。
- 基线确认：`git stash` 掉 `app/`、`tests/` 的工作区改动后复现命令仍失败，证明缺陷在改动前已存在。
- 全量 `uv run pytest -m general` 同样命中该失败。

## 已查明的根因事实链

失败由三个独立因素叠加造成，**并非此前怀疑的 monkeypatch 未还原**：

1. **导入期 dotenv 污染进程环境**：`app/main.py` 在模块顶层（约第 21 行）执行 `dotenv.load_dotenv()`。该调用在模块导入时就修改进程级 `os.environ`，而非在 `main()` 运行时。项目根的 `.env` 中含 `SEMANTIC_COMMAND_ENABLED=true`（本地开发配置；其中还含凭据，本提案不誊抄其值）。
2. **测试在收集期导入 `app.main`**：`tests/test_startup_index_rebuild.py` 顶部 `from app.main import main`，pytest 收集阶段导入该模块即触发上一步的 `load_dotenv()`，使 `SEMANTIC_COMMAND_ENABLED=true` 对**整个 pytest 会话**生效。佐证：在 `tests/conftest.py` 临时加入 autouse 探针，显示该变量在会话内**第一个测试进入之前**就已是 `'true'`，排除了"测试运行中泄漏"的假设。
3. **全局 fastembed stub 跨模块残留**：`tests/test_command_matching.py`（约第 17–28 行）在模块导入时把一个最小化的 `fastembed` stub 直接写入 `sys.modules["fastembed"]`（无 teardown），其中 `TextEmbedding` 只有 `__init__`、没有 `embed`。

三者交汇于 `test_startup_index_rebuild` 执行 `main()` 时调用 `build_command_matcher()`（`app/main.py`）：读到被污染的 `SEMANTIC_COMMAND_ENABLED=true` → 进入语义分支 → 局部导入 `semantic` 模块 → 构造 `SemanticCommandMatcher(FastEmbedEmbedder())`。而 `SemanticCommandMatcher.__init__` 会在启动时立即对目录短语做 embedding（`app/services/command_matching/semantic.py` 构造函数内的 `embedder.embed(...)`），此时 `fastembed` 是缺 `embed` 的 stub，于是抛出 `AttributeError`。

**顺序相关性解释**：单独跑 startup 测试时，环境变量虽为 true，但没有 stub，语义分支加载真实模型（本地已缓存）可正常构造，因此通过；与 `test_command_matching.py` 同跑时，stub 已占据 `sys.modules`，语义分支命中残缺 stub 才失败。

`test_startup_index_rebuild.py` 已 patch `MetadataStore`、`create_pipeline`、`LifecycleNotifier`、`BotService` 等外部依赖，**唯独没有隔离 `build_command_matcher`**，使真实 matcher 工厂在"被污染的环境 + 残缺 stub"下运行，是直接触发点。

## 影响面（blast radius）

- 不止 `SEMANTIC_COMMAND_ENABLED`：导入期 `load_dotenv()` 会把本地 `.env` 的全部变量（如 `LOG_LEVEL` 等）注入测试进程，任何"依赖环境变量默认值"的单测都可能在开发者本机被本地配置悄悄改变行为，CI 因无 `.env` 表现可能不同，存在"本地与 CI 不一致"的隐患。
- 模块级 `sys.modules["fastembed"]` stub 是为默认测试集设计的全局替身，其残缺接口与无 teardown 特性，会影响任何在 general 测试集里真实走进语义分支的代码路径。

## 修复方案（已定稿）

采用"装配边界纯化 + 显式参数注入"，从根上消除环境污染与不可注入问题。环境变量仍是**唯一**的产品侧控制手段（不新增 CLI 开关，与 `LOG_LEVEL` 的 env-only 处理保持一致），但读取与装配职责重新分层：

- **只有产品入口加载 `.env`**：把 `dotenv.load_dotenv()` 从 `app/main.py` 模块顶层移入 `main()` 函数入口，使 `import app.main` 不再产生修改进程环境的副作用；测试收集期不会被动加载本地 `.env`。
- **开关在配置层统一收口**：由 `parse_config()` 读取 `SEMANTIC_COMMAND_ENABLED`（env-only、无 CLI flag），解析为布尔 `semantic_command_enabled`，与其他配置项一致地挂在 config 上。
- **装配函数按显式入参选择**：`build_command_matcher(enabled: bool)` 不再在函数内部 `os.getenv`，纯按入参返回子串或语义匹配器；`main()` 以 `build_command_matcher(enabled=config.semantic_command_enabled)` 显式注入。
- **测试一律用显式参数控制装配，不依赖环境变量**：工厂选择测试改为直接传 `enabled=True/False`；startup 测试显式 patch/注入子串匹配器；匹配器使用逻辑本就通过构造参数注入 catalog/embedder，不受影响。
- **集中管理 fastembed 测试替身**：将 `test_command_matching.py` 模块级写入 `sys.modules["fastembed"]` 且无 teardown 的残缺 stub，收敛到 `tests/conftest.py` 统一安装，消除跨模块全局残留；语义验收会话仍可移除 stub 加载真实模型。

不采用"只在 startup 测试里 patch 匹配器"的最小止血做法——那只消除单个失败、不解决导入期污染根因；本方案同时落地导入纯度与测试环境隔离，并以显式参数注入贯通两者。

## What Changes

- 生产代码：`app/main.py`（`load_dotenv()` 移入 `main()`；`parse_config()` 增加 `semantic_command_enabled`；装配调用改为显式传参；抽出 `run_startup_index_check` 启动阶段函数）；`app/services/command_matching/__init__.py`（`build_command_matcher(enabled: bool)` 去掉内部环境读取）。
- 测试：重写 `tests/test_command_matching.py` 的工厂选择测试（显式入参，去除对 `SEMANTIC_COMMAND_ENABLED` 的 setenv/delenv）；将 `tests/test_startup_index_rebuild.py` 重写为针对 `run_startup_index_check` 的契约测试（不再整体跑 `main()`、不 import main 入口，放弃 main 接线测试）；将 fastembed stub 收敛到 `tests/conftest.py`；新增一个"导入 `app.main` 不加载 `.env`"的导入纯度回归测试。
- 不改变对外可观测行为：开关仍由 `SEMANTIC_COMMAND_ENABLED`（`true/1`）控制，默认子串、阈值 0.8、模型、匹配与疑问拦截逻辑均不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 —— 属装配与测试基础设施重构，不改变产品对外行为；环境变量控制语义保持不变，设置 `skip_specs: true`。）

## Impact

- 生产代码：`app/main.py`、`app/services/command_matching/__init__.py`（内部装配接口签名变更）。
- 测试：`tests/test_command_matching.py`、`tests/test_startup_index_rebuild.py`、`tests/conftest.py`，并新增一个导入纯度回归测试。
- 不涉及外部 API、依赖或数据迁移；环境变量名与控制语义不变。
- 安全提示：`.env` 含明文凭据，排查与提交时不得将其值写入任何变更文档或日志；本提案仅引用变量名。
