## Context

See proposal.md - Why。现状的关键事实（探索阶段已逐一核对）：

- `lib/` 六个模块的内部依赖是单向无环的：`handlers → file_storage`；`runner → lifecycle_notifier`（对 handlers 仅有 `TYPE_CHECKING` 引用）；store/downloader 不经 import 耦合 handlers，而是由 `app/main.py` 的 `create_pipeline()` 构造注入。
- `app/` 与 `lib/` 当前均无 `__init__.py`，依赖 pytest 配置 `pythonpath = ["."]` 以命名空间包方式工作；生产启动命令 `python -m app.main`，容器 `WORKDIR /app`。
- 全部 `lib.*` 引用点共 14 处文件：`app/main.py`、2 处模块内部互引、`tests/` 9 个文件；已归档 OpenSpec 变更中存在大量历史路径文本（不动）。

```
 迁移前:                          迁移后:
 app/main.py (装配)               app/main.py (装配)
   |--> lib.metadata_store          |--> app.services.metadata_store
   |--> lib.file_downloader         |--> app.services.file_downloader
   |--> lib.lifecycle_notifier      |--> app.services.lifecycle_notifier
   |--> lib.runner                  |--> app.core.runner
   |--> lib.handlers                |--> app.handlers (包, re-export)
                                      handlers.message --> app.utils.file_storage
                                      core.runner      --> app.services.lifecycle_notifier
```

## Goals / Non-Goals

**Goals:**

- 建立与现有依赖方向一致的四层包结构，并把"哪类代码放哪层"固化为可执行约定。
- 除导入路径与文件位置外零行为变化：类名、函数签名、日志名、运行时行为全部不变。
- 测试导入面最小化变动：`from app.handlers import PipelineHandler/CommandHandler/...` 与旧的 `from lib.handlers import ...` 同为包级导入。

**Non-Goals:**

- 不拆分 `handlers.py` 的五个类（保持单文件）。
- 不重构任何模块内部实现、不调整日志 logger 名称（如 `file-bridge.runner`）。
- 不修订已归档 OpenSpec 变更中的历史路径文本；不改变在途变更的需求范围与任务编号。
- 不处理 FastAPI 应用实例化本身（由在途变更 `integrate-fastapi-framework` 负责）。

## Decisions

### D1：四层分包 core / handlers / services / utils

| 包 | 放入模块 | 准入标准 |
|---|---|---|
| `app/core` | runner | 生命周期与运行时编排，不写具体业务 |
| `app/handlers` | message | 紧贴钉钉 SDK 的消息回调适配与处理链 |
| `app/services` | file_downloader、lifecycle_notifier、metadata_store | 持有外部资源（HTTP client / SQLite / SDK client）的有状态网关 |
| `app/utils` | file_storage | 无状态纯函数，不依赖项目内任何其他包 |

分层依赖规则（单向，迁移后仍无环）：`utils` 不依赖任何项目内包；`services` 不依赖 handlers/core；`handlers` 可依赖 services、utils；`core` 位于编排顶端；`main.py` 负责跨层装配与依赖注入。

- 备选 A（三层 core/handlers/utils）：把 downloader/store 放进 utils，会使纯函数包混入有状态外部网关，放弃。
- 备选 C（按领域 lifecycle/pipeline/files）：与 OpenSpec capability 对齐直观，但偏离团队选定的分层命名，且 files 包内仍混三种性质，放弃。
- 未来 FastAPI 的 HTTP 路由按此规则落在与 core 平级的新包（如 `app/api/`），本次不提前创建空包。

### D2：handlers 保持单文件，命名 message.py，包 `__init__` re-export

`lib/handlers.py` 整体 `git mv` 为 `app/handlers/message.py`（避免 `handlers/handlers.py`），不拆类。`app/handlers/__init__.py` 从 `.message` re-export `BaseMessageHandler`、`PipelineHandler`、`CommandHandler`、`MediaFileHandler`、`CalcBotFallbackHandler`，使所有测试与 main.py 维持 `from app.handlers import ...` 的包级导入面。选择单文件是因为在途变更 `support-group-chat-messages` 即将对 `MediaFileHandler` 与 `process()` 做大改，先拆分会放大两边的 diff 冲突。

### D3：补齐显式 `__init__.py`

新增 `app/__init__.py`、`app/core/__init__.py`、`app/handlers/__init__.py`、`app/services/__init__.py`、`app/utils/__init__.py`（除 handlers 外均为空文件），由命名空间包转为 regular package。备选是继续依赖隐式命名空间包；选显式包以消除 pytest 根目录插入与 IDE 解析的歧义，零运行时代价。

### D4：迁移用 git mv，引用按层批量替换

6 个文件一律 `git mv` 保留历史。导入路径映射：

| 旧路径 | 新路径 |
|---|---|
| `lib.runner` | `app.core.runner` |
| `lib.handlers` | `app.handlers` |
| `lib.lifecycle_notifier` | `app.services.lifecycle_notifier` |
| `lib.file_downloader` | `app.services.file_downloader` |
| `lib.metadata_store` | `app.services.metadata_store` |
| `lib.file_storage` | `app.utils.file_storage` |

替换顺序：先移动文件与建包 → 改包内互引（message.py、runner.py）→ 改 main.py → 改 tests → 改 Dockerfile/AGENTS.md，每类替换后以全仓 grep 验证无残留 `lib.`/`lib/` 代码引用。

### D5：在途变更只修订前瞻性落点，历史叙述不动

`support-group-chat-messages` 中 3 处指向"未来要改的文件"的 `lib/handlers.py`（proposal.md:27、design.md:3、tasks.md 2.1）改为 `app/handlers/message.py`；2 处 `lib/config.py` 是对已归档变更 simplify-config-entry 的历史叙述，保留原文。`integrate-fastapi-framework` 经 grep 确认无 lib 路径引用，不动。

## Risks / Trade-offs

- [导入点漏改导致 ImportError] → 引用面已在探索阶段全量清点（14 个文件），迁移后全仓 grep 兜底，并以 `uv run pytest` 全量 + `python -c "import app.main"` 冒烟验证。
- [re-export 引入循环导入] → `handlers/__init__.py` 只单向导入 `.message`，而 message 仅依赖 `app.utils`；core 对 handlers 是 `TYPE_CHECKING` 级引用，运行时无环，风险已在依赖图上排除。
- [容器 WORKDIR `/app` 与 Python 包 `app/` 同名] → 容器内代码位于 `/app/app/`，`python -m app.main` 解析的是工作目录下的包目录，不与 WORKDIR 本身冲突；启动命令无需修改。
- [内部路径变更影响外部脚本] → 项目 `package = false` 为独立应用，无发布的 import API；全仓 grep 确认除 `app/`、`tests/` 外无任何 Python 入口引用 `lib`（AGENTS.md 中保留的 `script/` 条目为结构约定，当前磁盘上无对应脚本，未来新增脚本须使用新包路径）。
- [回滚] → 变更集中在一个提交，直接 `git revert` 即可，无数据或配置迁移。

## Migration Plan

1. `git mv` 六个模块到 D1/D2 目标位置，删除空的 `lib/`。
2. 新增五个 `__init__.py`（handlers 包含 re-export）。
3. 按 D4 映射更新包内互引、`app/main.py`、9 个测试文件的导入。
4. 更新 `Dockerfile`（删 COPY lib）与 `AGENTS.md`（项目结构段）。
5. 修订在途变更 3 处路径文本。
6. 验证：全仓 grep 确认无残留 `lib.`/`lib/` 代码引用；`uv run pytest` 全量通过；`python -m app.main --help` 或 import 冒烟确认入口可用。

回滚策略：整体作为单个提交，失败时 `git revert` 该提交恢复原状。
