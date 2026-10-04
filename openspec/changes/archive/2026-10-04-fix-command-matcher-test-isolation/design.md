# Design: fix-command-matcher-test-isolation

## Context

默认测试集在多文件同跑时稳定失败（`test_startup_index_rebuild` 报 `'_StubTextEmbedding' object has no attribute 'embed'`）。根因见 proposal：`app/main.py` 在模块顶层执行 `dotenv.load_dotenv()`，测试收集期 `from app.main import main` 即把本地 `.env` 的 `SEMANTIC_COMMAND_ENABLED=true` 注入整个 pytest 进程；而 `build_command_matcher()` 在函数内部自行 `os.getenv` 决定后端，无法被测试注入；叠加 `test_command_matching.py` 模块级写入 `sys.modules["fastembed"]` 的残缺 stub，最终在语义分支构造 matcher 时崩溃。

当前配置收口方式不对称：`CLIENT_ID`/`OUTPUT_DIR`/`LOG_LEVEL` 等都经 `parse_config()` 读入 config 再显式传递，唯独匹配器开关由装配函数直接抓全局环境。本变更把这一处对齐到既有模式。

## Goals / Non-Goals

**Goals:**
- 使 `import app.main` 无副作用：`.env` 只在产品入口 `main()` 内加载。
- 匹配器装配可注入：`build_command_matcher` 按显式布尔入参选择后端，不读环境变量。
- 测试以显式参数控制装配，不依赖进程环境，保证本地/CI、任意执行顺序结果一致。
- 消除 fastembed 残缺 stub 的跨模块全局残留。

**Non-Goals:**
- 不新增 CLI 开关；`SEMANTIC_COMMAND_ENABLED` 保持 env-only，与 `LOG_LEVEL` 处理一致。
- 不改变开关的取值语义（`true/1` 大小写不敏感为真，其余为假）、默认后端（子串）、阈值（0.8）、模型与疑问拦截行为。
- 不重构其他配置项的读取方式，不顺带修复无关问题。

## Decisions

### D1: `load_dotenv()` 移入 `main()` 入口
从 `app/main.py` 模块顶层删除 `dotenv.load_dotenv()`，改为在 `main()` 函数体最前面调用。`parse_config()` 仍在其后执行，故产品运行时 env 照常可用；而任何 `import app.main`（含测试收集）都不再修改 `os.environ`。已确认全仓库仅 `main.py:21` 一处加载 dotenv，无其他模块依赖导入期加载。备选（保留顶层、在 conftest 里清空 env）被否决：污染根因留在生产代码，每个新 importer 都可能再踩。

### D2: 开关在 `parse_config()` 统一收口，env-only
仿照 `LOG_LEVEL` 的 env-only 写法，在 `parse_config()` 用 `parser.set_defaults(semantic_command_enabled=...)` 读取，不注册 CLI flag。真假值集合（`{"true","1"}`，strip+lower）只在 `command_matching` 包内定义一处，导出纯函数 `parse_enabled(raw: str | None) -> bool` 供 config 层复用，避免在 main 重复字面量集合。

### D3: `build_command_matcher(enabled: bool)` 纯按入参装配
装配函数改为接收布尔参数，删除函数体内的 `os.getenv`，保留启动 INFO 日志与"语义后端局部 import、构造失败即终止、不静默回退"的行为。`main()` 调用点改为 `build_command_matcher(enabled=config.semantic_command_enabled)`。这是内部接口签名变更，同步更新调用点与工厂测试；不影响外部 API。

### D4: 测试用显式参数，不用环境变量
工厂选择测试由 `monkeypatch.setenv("SEMANTIC_COMMAND_ENABLED", ...)` 改为直接 `build_command_matcher(enabled=True/False)`；语义后端仍通过 monkeypatch 替换 `SemanticCommandMatcher`/`FastEmbedEmbedder` 类来避免真实加载（这部分与 env 无关，保留）。

### D5: 抽出启动索引校验阶段，startup 测试收窄为契约测试
当前索引校验逻辑（建 store → `rebuild_index()` → 记计数日志）内联在 `main()` 中，测试为触发它只能 `from app.main import main` 并整体跑 `main([])`，被迫 mock 一圈无关 SDK 协作者、用 `SystemExit` 打断阻塞，且该 import 在收集期即触发 dotenv。将这段逻辑抽为独立函数 `run_startup_index_check(metadata_store, logger)`（仅做校验+计数日志），`main()` 内对应三行改为一次调用。测试重写为针对该函数的纯契约测试，直接 `from app.main import run_startup_index_check`，以 Mock store 断言"调用一次 + 计数日志"，不再 import `main`、不碰 env/SDK、无需 `SystemExit`。
**不引入通用启动阶段框架**：6 个启动步骤中仅此 1 步含业务逻辑，其余为线性 SDK 接线；`main()` 作为组合根保持朴素线性、不做逐接线测试（方案 2）。框架的触发阈值（出现第 2 个共享启动步骤的入口、或 ≥3 个按配置启停的可选阶段）记入项目记忆，本次不实现。

### D6: fastembed stub 收敛到 conftest，且必须在收集期安装
`test_command_matching.py` 顶层 `from ...semantic import ...` 会在**收集/导入期**触发 `semantic.py` 的 `from fastembed import TextEmbedding`，早于任何 fixture，因此 stub 不能用 fixture 安装。做法：把 stub 的模块级注册（含 `_file_bridge_test_stub` 标记与记录 kwargs 的 `_StubTextEmbedding`）整体移到 `tests/conftest.py` 顶层——conftest 先于测试模块导入，保证 general 集收集期 `fastembed` 已被替身占据、永不加载原生栈；删除 `test_command_matching.py` 内的重复注册。语义验收（`-m semantic`）会话中，`test_semantic_command_smoke.py` 的 fixture 仍按既有逻辑弹出 stub 并重新导入真实模块（该会话只收集 semantic 标记用例，弹出后不影响他者）。

### D7: 增加导入纯度回归测试
新增一个基于子进程的测试：在清空 `SEMANTIC_COMMAND_ENABLED` 的全新解释器中，于工程根目录 `import app.main`，断言该变量仍不存在（即导入未触发 `.env` 加载）。该用例在修复前失败、修复后通过，作为防回退保护；不读取也不断言 `.env` 中任何凭据值。

## Risks / Trade-offs

- [`build_command_matcher` 改签名漏掉调用点] → 全仓库仅此一处生产调用（`main.py`）与若干测试；改后跑默认集与语义集确认。
- [stub 移到 conftest 后语义会话加载真实模型受影响] → 保留 smoke fixture 的弹 stub 逻辑，并以 `pytest -m semantic` 实测 4 项通过验证。
- [子进程回归测试依赖工程根存在 `.env`] → 断言只针对"导入是否产生副作用"（导入前后该变量不变），不依赖 `.env` 的具体取值；在无 `.env` 的 CI 环境下该断言同样成立。
