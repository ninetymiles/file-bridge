## Why

核心运行模块全部位于顶层 `lib/`，而应用入口 `app/main.py` 反而以"外部消费者"身份跨顶层导入，包结构与实际分层倒置；同时 `lib/` 内六个模块性质混杂（编排、消息适配、外部系统网关、纯函数工具）无层级区分。在途变更 `integrate-fastapi-framework`（0/6）即将在 `app/` 内引入 HTTP 层，在途变更 `support-group-chat-messages`（0/12）尚未动工，此刻迁移可让后续两个变更直接落在新结构上，避免二次搬迁。

## What Changes

- 将 `lib/` 六个模块按职责迁入 `app/` 四个二级包，**纯物理重组，不改任何运行时行为**：
  - `lib/runner.py` → `app/core/runner.py`（生命周期编排）
  - `lib/handlers.py` → `app/handlers/message.py`（消息管道与处理器，保持单文件不拆分类）
  - `lib/file_downloader.py`、`lib/lifecycle_notifier.py`、`lib/metadata_store.py` → `app/services/`（对外部系统的有状态网关）
  - `lib/file_storage.py` → `app/utils/file_storage.py`（无状态纯函数）
- 新增 `app/__init__.py` 及四个子包的 `__init__.py`，由命名空间包转为显式 regular package；`app/handlers/__init__.py` re-export 五个处理器类，保持对外导入面 `from app.handlers import ...` 不变。
- 更新全部导入路径：`app/main.py`（5 组）、`app/handlers/message.py`（1 处）、`app/core/runner.py`（2 处，含 TYPE_CHECKING）、`tests/` 下 9 个测试文件；迁移后删除空的 `lib/` 目录。
- 更新部署与文档：`Dockerfile` 删除 `COPY lib/ ./lib/`；`AGENTS.md` 项目结构段删除 `lib/` 条目，并将 `app/` 条目更新为 main.py 加 core/handlers/services/utils 四个二级包的描述；`script/`、`tests/`、`third-party/`、`docs/`、`openspec/` 等其余条目及其他章节一律保持原样。
- 同步修订在途变更 `support-group-chat-messages` 的 proposal.md、design.md、tasks.md 中 3 处前瞻性落点表述 `lib/handlers.py` → `app/handlers/message.py`，需求范围与任务编号不变；其中对已归档变更的历史叙述（`lib/config.py` 已内联）保持原样。
- **内部导入路径变更（BREAKING for internal imports）**：所有 `lib.*` 导入路径失效；本项目 `pyproject.toml` 声明 `package = false`，为独立应用而非发布库，无外部消费者。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。本变更是纯目录与导入路径重组，不改变任何 spec 级行为需求，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码移动**：`lib/` 6 个模块以 `git mv` 迁入 `app/` 子包以保留文件历史；新增 5 个 `__init__.py`。
- **引用更新**：`app/main.py`、2 个迁移模块内部互引、`tests/` 9 个文件（test_command_handler、test_media_file_handler、test_pipeline、test_drain、test_file_downloader、test_file_storage、test_metadata_store、test_lifecycle_notifier、test_runner）；test_config、test_integration 已引用 `app.main`，不受影响。
- **部署**：`Dockerfile` 的 COPY 指令；容器工作目录 `/app` 与 Python 包 `app/` 同名但不冲突，启动命令 `python -m app.main` 不变。
- **文档**：`AGENTS.md` 项目结构段。
- **OpenSpec**：在途变更 `support-group-chat-messages` 3 处路径文本；已归档变更作为历史记录不动。
- **依赖与配置**：无新增依赖，`pyproject.toml` 的 pytest `pythonpath = ["."]` 配置不变。
