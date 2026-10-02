# Proposal: default-fastembed-cache-dir

## Why

语义匹配器的模型缓存目前完全依赖 `FASTEMBED_CACHE_PATH` 环境变量；不设置时 fastembed 回落到系统临时目录（`$TMPDIR/fastembed_cache`），重启或清理临时目录后模型丢失需重新下载。模型缓存是工程内一份约 95MB 的固定运行时产物，其默认位置应由工程自身决定，而不是要求每个运行环境（本地开发、pytest）都在 `.env` 中显式声明。

## What Changes

- 语义匹配器构造 fastembed 模型时，默认缓存目录固定为工程根下的 `cache/`（以代码文件位置锚定，不依赖启动时 cwd）；`FASTEMBED_CACHE_PATH` 环境变量仍可覆盖该默认值。
- Docker 部署改为将 named volume 直接挂载到容器内工程根 `/app/cache`，删除 compose 中不再需要的 `FASTEMBED_CACHE_PATH` 环境变量声明；容器与本地自此使用同一条"工程根 cache 目录"约定。
- 删除本地 `.env` 与 `.env.example` 中的 `FASTEMBED_CACHE_PATH` 声明（默认路径已覆盖本地与容器场景，该出口不在配置样例中暴露；覆盖机制仍保留在代码中）。
- 移除 `tests/conftest.py` 中仅为让 pytest 读取该变量而加入的 `load_dotenv()`，测试恢复不加载 `.env` 的既有约定。
- 新增默认缓存目录解析的单元测试（不加载真模型）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `semantic-command`: "可选的本地 embedding 语义匹配"需求中模型缓存位置的约定变化——默认使用工程根 `cache/` 目录，`FASTEMBED_CACHE_PATH` 降为可选覆盖项。

## Impact

- 代码：`app/services/command_matching/semantic.py`（`FastEmbedEmbedder` 构造时解析并显式传入 cache_dir）。
- 测试：`tests/test_command_matching.py`（缓存目录解析单测）、`tests/conftest.py`（移除 load_dotenv）。
- 部署配置：`docker-compose.yml`（卷挂载点改为 `/app/cache`，删除环境变量）、`.env.example`（注释更新）。
- 不引入新依赖；fastembed 的 `cache_dir` 显式参数与 `FASTEMBED_CACHE_PATH` 覆盖语义均为其现成能力。
