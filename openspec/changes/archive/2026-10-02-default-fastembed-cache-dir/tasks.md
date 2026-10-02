# Tasks: default-fastembed-cache-dir

## 1. 代码默认缓存目录

- [x] 1.1 修改 `app/services/command_matching/semantic.py`：以模块常量定义工程根缓存目录（`Path(__file__).resolve().parents[3] / "cache"`，英文注释说明锚点层级）；`FastEmbedEmbedder` 构造时按 `FASTEMBED_CACHE_PATH` 非空则用之、否则用默认目录的规则解析，并显式传给 `TextEmbedding(cache_dir=...)`
- [x] 1.2 扩展 `tests/test_command_matching.py` 的 fastembed 桩（记录 `TextEmbedding` 构造参数），新增两个单测：env 显式设置时传入 env 路径；env 未设置/为空时传入工程根 `cache` 的绝对路径；均不加载真模型
- [x] 1.3 删除 `tests/conftest.py` 中的 `load_dotenv()` 调用、import 与相关注释，恢复测试不加载 `.env` 的约定
- [x] 1.4 `uv run pytest`（general 默认集）全绿

## 2. 本地与部署配置

- [x] 2.1 从本地 `.env` 删除 `FASTEMBED_CACHE_PATH` 行（本地文件，不入库；使用者操作，实施时确认删除）
- [x] 2.2 从 `.env.example` 删除 `FASTEMBED_CACHE_PATH` 注释与示例行（覆盖机制保留在代码中，但不作为配置项暴露）
- [x] 2.3 修改 `docker-compose.yml`：named volume 挂载点 `/cache` 改为 `/app/cache`，删除 `environment` 中的 `FASTEMBED_CACHE_PATH`（volume 名不变，既有缓存数据随卷复用，无需重下）

## 3. 验证

- [x] 3.1 在 `.env` 无该变量的前提下，`HF_HUB_OFFLINE=1 uv run pytest -m semantic` 离线通过，证明默认工程根 `cache` 生效
- [x] 3.2 临时设置 `FASTEMBED_CACHE_PATH` 指向其他目录启动工厂级验证（或借 1.2 单测），确认覆盖语义；验证后不留临时代码
- [x] 3.3 `openspec validate default-fastembed-cache-dir --strict` 通过
