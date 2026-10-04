# Tasks

## 1. 生产装配解耦

- [x] 1.1 将 `app/main.py` 模块顶层的 `dotenv.load_dotenv()` 移入 `main()` 函数体最前面（`parse_config()` 之前），并保留 dotenv 导入
- [x] 1.2 在 `app/services/command_matching/__init__.py` 导出纯函数 `parse_enabled(raw: str | None) -> bool`（复用现有 `{"true","1"}`、strip+lower 判定），保持真值集合仅此一处定义
- [x] 1.3 在 `parse_config()` 中以 `parser.set_defaults(...)` 增加 env-only 的 `semantic_command_enabled`（读取 `SEMANTIC_COMMAND_ENABLED`，经 `parse_enabled` 解析），不新增 CLI flag
- [x] 1.4 将 `build_command_matcher()` 改为 `build_command_matcher(enabled: bool)`，删除函数体内 `os.getenv`，保留启动日志/局部 import/构造失败即终止行为；`main()` 调用点改为 `build_command_matcher(enabled=config.semantic_command_enabled)`
- [x] 1.5 从 `main()` 抽出启动索引校验阶段为 `run_startup_index_check(metadata_store, logger)`（执行 `rebuild_index()` 并记录 cleaned/remaining 计数日志），`main()` 内对应三行替换为一次调用；不引入通用启动阶段框架

## 2. 测试改为显式参数与集中替身

- [x] 2.1 重写 `tests/test_command_matching.py` 的工厂选择测试：以 `build_command_matcher(enabled=True/False)` 直接断言后端类型，删除对 `SEMANTIC_COMMAND_ENABLED` 的 setenv/delenv；保留用 monkeypatch 替换语义类来避免真实加载的断言
- [x] 2.2 将 `tests/test_startup_index_rebuild.py` 重写为针对 `run_startup_index_check` 的契约测试：改为 `from app.main import run_startup_index_check`，删除 `from app.main import main`；以 Mock store 断言"rebuild_index 调用一次 + cleaned/remaining 计数日志"，不再 mock SDK/环境变量、不再需要 `SystemExit`；不保留 `main()` 接线测试（方案 2）
- [x] 2.3 将 fastembed 残缺 stub（含 `_file_bridge_test_stub` 标记与 `_StubTextEmbedding`）的模块级注册从 `tests/test_command_matching.py` 移至 `tests/conftest.py` 顶层，删除测试文件中的重复注册；确认 `test_semantic_command_smoke.py` 弹 stub 逻辑无需改动
- [x] 2.4 新增导入纯度回归测试：子进程中清空 `SEMANTIC_COMMAND_ENABLED` 后于工程根 `import app.main`，断言导入前后该变量均不存在；不读取 `.env` 凭据值

## 3. 验证

- [x] 3.1 `uv run pytest -m general` 全绿；并分别验证单独跑 `tests/test_startup_index_rebuild.py`、以及与 `tests/test_command_matching.py` 同跑（含打乱/逆序）结果一致
- [x] 3.2 `uv run pytest -m semantic` 通过（真实模型路径在 stub 被弹开后仍正常）
- [x] 3.3 在本地 `.env` 存在（`SEMANTIC_COMMAND_ENABLED=true`）与临时移走 `.env` 两种状态下分别运行默认集，结果一致（本地/CI 一致性）
- [x] 3.4 `openspec validate fix-command-matcher-test-isolation --strict`
