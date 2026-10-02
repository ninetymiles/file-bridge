# Design: default-fastembed-cache-dir

## Context

见 proposal.md。现状事实：

- `FastEmbedEmbedder`（`app/services/command_matching/semantic.py`）是工程内 fastembed 的唯一构造点，当前以 `TextEmbedding(model_name=...)` 构造，未传 `cache_dir`。
- fastembed `define_cache_dir` 的解析顺序为：显式 `cache_dir` 参数 > `FASTEMBED_CACHE_PATH` 环境变量 > `$TMPDIR/fastembed_cache`。即一旦代码显式传参，环境变量即失效，覆盖语义必须由我们自己的代码保留。
- fastembed 在解析时会对目标目录执行 `mkdir(parents=True, exist_ok=True)`，目录无需预建。
- 容器 WORKDIR 为 `/app`，Dockerfile 只 `COPY app/`；本地工程根 `cache/` 已在 `.gitignore`。
- `tests/conftest.py` 中的 `load_dotenv()` 是上一变更专为让 pytest 读到该变量而加的；general 测试集本身不依赖 `.env`。

## Goals / Non-Goals

**Goals:**

- 本地开发与 pytest 无需任何 `.env` 配置即把模型缓存固定在工程根 `cache/`。
- 容器与本地使用同一条"工程根 cache 目录"约定，部署配置不再重复声明路径。
- 保留 `FASTEMBED_CACHE_PATH` 作为显式覆盖手段（自定义路径/离线分发等场景）。

**Non-Goals:**

- 不改模型、阈值、匹配逻辑与懒加载边界。
- 不做模型文件手工管理/镜像预烤（TODO 中另有后续规划）。
- 不把缓存路径做成 app 配置项（Config 对象）；仅一个环境变量覆盖 + 固定默认值，不引入配置面。

## Decisions

### 1. 默认路径在 fastembed 边界模块内以 `__file__` 锚定解析

`semantic.py` 位于 `app/services/command_matching/semantic.py`，`Path(__file__).resolve().parents[3]` 即工程根（本地为仓库根，容器内为 `/app`），下挂 `cache/`。解析规则：

```
cache_dir = os.getenv("FASTEMBED_CACHE_PATH") or str(<工程根>/cache)
TextEmbedding(model_name=..., cache_dir=cache_dir)
```

- 选 `__file__` 而非 `Path.cwd()`：缓存位置不随启动目录漂移（pytest、`python -m app.main`、其他 cwd 调用结果一致）。
- 选"代码内 env or 默认值 + 显式传参"而非 `os.environ.setdefault`：后者隐式改写进程全局环境，读者无法从构造点察觉；显式局部表达式意图清晰、可直接单测。
- 空字符串与未设置同等对待（`or` 语义），与 spec"未设置或为空时使用默认目录"一致。

### 2. 容器卷直接挂 `/app/cache`，删除 compose 环境变量

named volume `file-bridge-storage` 的挂载点由 `/cache` 改为 `/app/cache`，删除 `FASTEMBED_CACHE_PATH: /cache`。容器 WORKDIR 即 `/app`，代码默认值解析结果正是挂载点，本地与容器路径规则合流，compose 不再需要知道缓存目录这个实现细节。

### 3. 测试策略

- 缓存解析单测放在 `tests/test_command_matching.py`（该文件已在导入时以桩替换 fastembed）：扩展桩 `TextEmbedding` 记录构造参数，monkeypatch 环境变量两种情形，断言传入的 `cache_dir`——env 有值时为 env 值；env 缺失时为工程根 `cache` 绝对路径。不加载真模型。
- semantic smoke 不新增断言：移除 `.env` 声明后离线跑通 `-m semantic` 即证明默认目录生效，本身已是行为闭环。
- 移除 `tests/conftest.py` 的 `load_dotenv()` 及其 import 与注释，恢复 general 集不读 `.env` 的约定。

## Risks / Trade-offs

- [默认路径锚定依赖 `semantic.py` 在包内的目录层级（parents[3]）] → 该层级被包结构固定，移动文件属于显式重构；以常量命名并加英文注释标明锚点，单测以工程根绝对路径兜底防漂移。
- [既有部署若已在 named volume `/cache` 中缓存模型，改挂 `/app/cache` 后首次启动需重新下载] → 同一 named volume 可改挂新路径复用数据（volume 内容与挂载点无关），实际无重下；在迁移步骤中注明。
- [删除 conftest 的 load_dotenv 后，若将来有测试需要 `.env` 变量需另行处理] → 测试应保持无环境依赖（边界处 monkeypatch），这正是既有约定；接受。
