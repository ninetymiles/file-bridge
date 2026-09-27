## 1. 建包与文件移动

- [x] 1.1 用 `git mv` 将 `lib/runner.py` 移至 `app/core/runner.py`，`lib/handlers.py` 移至 `app/handlers/message.py`，`lib/file_downloader.py`、`lib/lifecycle_notifier.py`、`lib/metadata_store.py` 移至 `app/services/`，`lib/file_storage.py` 移至 `app/utils/file_storage.py`；确认 `git status` 显示为 rename 且 `lib/` 目录已不存在
- [x] 1.2 新增 `app/__init__.py`、`app/core/__init__.py`、`app/services/__init__.py`、`app/utils/__init__.py` 四个空文件，确认文件存在
- [x] 1.3 在 `app/handlers/__init__.py` 中从 `.message` re-export `BaseMessageHandler`、`PipelineHandler`、`CommandHandler`、`MediaFileHandler`、`CalcBotFallbackHandler` 五个类，确认 `python -c "from app.handlers import PipelineHandler, CommandHandler, MediaFileHandler, CalcBotFallbackHandler, BaseMessageHandler"` 可执行（此时包内互引尚未改，预期可能失败的话以 2.1 完成后为准）

## 2. 导入路径更新

- [x] 2.1 更新包内互引：`app/handlers/message.py` 的 `from lib.file_storage import save_file` 改为 `from app.utils.file_storage import save_file`；`app/core/runner.py` 的 `from lib.lifecycle_notifier import ...` 改为 `app.services.lifecycle_notifier`，TYPE_CHECKING 段的 `from lib.handlers import PipelineHandler` 改为 `from app.handlers import PipelineHandler`；grep 确认迁移后的 app/ 内无 `lib.` 残留
- [x] 2.2 更新 `app/main.py` 第 10-19 行 5 组 import 为新路径（metadata_store/file_downloader/lifecycle_notifier 走 `app.services`，runner 走 `app.core`，处理器走 `app.handlers`），确认 `python -c "import app.main"` 无 ImportError
- [x] 2.3 更新 9 个测试文件导入：test_runner(`app.core.runner`)、test_lifecycle_notifier(`app.services.lifecycle_notifier`)、test_file_downloader(`app.services.file_downloader`)、test_metadata_store(`app.services.metadata_store`)、test_file_storage(`app.utils.file_storage`)、test_command_handler/test_media_file_handler/test_pipeline/test_drain(`app.handlers`，test_drain 内还有 1 处 file_downloader 延迟导入)；grep 确认 `tests/` 内无 `from lib` 残留

## 3. 部署与文档

- [x] 3.1 修改 `Dockerfile` 删除 `COPY lib/ ./lib/` 一行（保留 `COPY app/ ./app/`），人工核对 COPY 段与新结构一致
- [x] 3.2 更新 `AGENTS.md` 项目结构段：删除 `lib/ - 核心支持模块` 条目，并将 `app/` 条目更新为描述 main.py 与 core/handlers/services/utils 四个二级包；`script/`、`tests/`、`third-party/`、`docs/`、`openspec/` 等其余条目及其他章节一律不改；人工核对 diff 中仅 lib 行删除、app 行更新

## 4. 在途变更文本修订

- [x] 4.1 修订 `openspec/changes/support-group-chat-messages/` 的 proposal.md:27、design.md:3、tasks.md 2.1 三处 `lib/handlers.py` 为 `app/handlers/message.py`；保留 design.md:60 与 tasks.md 1.1 中 `lib/config.py` 的历史叙述不变；人工核对需求范围与任务编号未变
- [x] 4.2 grep 确认 `integrate-fastapi-framework/` 无 lib 路径引用（无需修改），全仓 `lib/` 文本残留仅剩已归档变更中的历史记录

## 5. 验证

- [x] 5.1 全仓 grep `from lib|import lib` 确认 Python 代码（app/、tests/ 及任何脚本入口）零残留，仅 openspec 归档目录允许存在历史文本
- [x] 5.2 运行 `uv run pytest` 全量测试通过（迁移前基线为 49 passed，用例数与断言行为不变）
- [x] 5.3 运行 `python -m app.main --help`（或等效 import 冒烟）确认入口可正常加载且参数解析正常；运行 `openspec validate restructure-app-packages --strict`（如该版本支持）确认变更工件校验通过
