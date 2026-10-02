## Context

现有 `CommandHandler` 中唯一的命令匹配是硬编码子串判断（`"重建索引" in content`），命令知识、匹配方式、执行逻辑三者耦合。工程为 Python 3.14 + 异步事件循环架构，全部测试为无网络、毫秒级。已核实 fastembed 0.8.1 支持 Python 3.14，其底层 onnxruntime 自 1.24.1 起提供 cp314 wheel；其内置模型注册表不含 multilingual-e5-small，可用的中文轻量模型为 `BAAI/bge-small-zh-v1.5`（512 维，量化 ONNX 约 30MB，无 query/passage 前缀约定），故选型为该模型而非设计初稿的 e5-small。本次不一次性切换匹配方式：语义能力与完整依赖随工程/镜像内置，但运行时默认保留子串匹配，语义匹配由环境变量开关灰度启用。手工下载/自管理本地 ONNX 模型的方案已评估，本期不做，记入 TODO 后续规划。详见 proposal.md。

```
启动 main() (env: SEMANTIC_COMMAND_ENABLED)
  false/未设置 (默认)                     true
       |                                   |
       v                                   v
  SubstringCommandMatcher          工厂分支才 import .semantic 模块
  (不导入推理库, 纯目录短语包含)       -> 模块顶层 import fastembed (加载失败 -> 显式报错终止)
       |                            FastEmbedEmbedder("BAAI/bge-small-zh-v1.5")
       |                            首启 HF 下载 / 之后缓存 (HF_TOKEN, HF_HUB_OFFLINE)
       |                            短语原文一次性 embed -> 内存矩阵 (N,512)
       +---------------+-----------------+
                       |
                       v  logger.info("Command matcher: substring|semantic (model=...)")
             create_pipeline -> CommandHandler(matcher, dispatch_table)

每条消息: 提取/合并文本 -> 归一化(去 <imgN>, 折叠空白; 空串短路)
  Substring: 短语 in text ? id : None
  Semantic:  text 原文 -> to_thread(embed) -> dot 矩阵 -> max>=0.8 ? id : None
             -> dispatch_table[id](...) 执行
```

## Goals / Non-Goals

**Goals:**
- 语义支持作为内置能力随工程与 Docker 镜像完整分发；部署仅靠 `.env` 开关即可切换，无需额外安装。
- 默认运行行为与现状逐字一致：不导入推理库、不加载模型，不承担推理开销。
- 匹配机制与具体命令解耦：matcher 只返回 command id，handler 只按分发表执行，新增命令只加数据与回调。
- 启用语义时模型推理不阻塞事件循环，模型在启动期就绪；启动日志明确显示当前匹配器类型。
- 默认测试集保持无模型加载、秒级完成；真模型验证以独立 marker 显式触发并可长期回归。

**Non-Goals:**
- 不做运行期动态切换匹配器（仅启动时按环境变量装配一次）。
- 不做手工模型下载/本地模型路径管理（不引入模型路径环境变量），该方向记入 TODO。
- 不做命令短语的配置化/持久化（目录是代码常量）；阈值、模型名不做环境变量配置。
- 不重构命令回复内容与回调之外的既有行为；不处理 Docker 镜像预烤模型与容器缓存卷（镜像内置依赖但不含模型权重）。

## Decisions

### 1. `app/services/command_matching/` 包：接口与两个实现各自成文件
```
command_matching/
  __init__.py   build_command_matcher() 装配工厂，对外 re-export 公共类型
  base.py       BaseCommandMatcher(ABC)：async match(text)->id|None；
                normalize_command_text() 共享归一化（剥 <imgN>/折叠空白）
  catalog.py    COMMAND_CATALOG（首期仅 rebuild_index，两个实现共享的数据）
  substring.py  SubstringCommandMatcher（仅标准库；短语包含、目录顺序消歧）
  semantic.py   FastEmbedEmbedder + SemanticCommandMatcher、模型名/阈值常量；
                顶层 import fastembed/numpy（普通模块级导入，无特例）
```
统一 async 签名：子串实现内部是同步逻辑直接返回，语义实现内部经 `to_thread`。handler 先调 `normalize_command_text`，空串短路，再把干净文本交给 matcher，两个实现不重复归一化。`FastEmbedEmbedder` 是系统边界薄封装，构造时初始化 `TextEmbedding(model_name=...)`（触发下载/加载），对外仅暴露同步 `embed(list[str]) -> np.ndarray`；`SemanticCommandMatcher` 依赖极小 embedder 协议，持有目录、短语向量矩阵与阈值。
两个实现同协议、可替换，是标准的接口+实现分界，不属于过度拆分；再细拆 embedder/常量独立文件则无必要。

### 2. fastembed 主依赖内置，懒加载边界是 semantic 模块而非函数内 import
`pyproject.toml` 直接声明主依赖 `fastembed`（传递 onnxruntime/numpy），`uv sync` 与 Docker 镜像的 `uv sync --no-dev` 均完整安装，部署侧零额外步骤。包 `__init__.py` 顶层只导入 base/catalog/substring，导入链上没有 fastembed；`semantic.py` 内部使用**普通顶层导入** `import fastembed`，该模块仅在工厂的开关启用分支中被 `from .semantic import ...` 加载——即标准的"可选后端模块"模式：启用哪个后端才导入哪个后端的模块，而非在函数体内打延迟导入补丁。默认子串模式因此不支付 onnxruntime 导入开销，开关开启时导入/加载抛错自然向上传播终止进程，不加多余 try-catch。备选（可选依赖组、部署时 `--extra` 安装）被否：需求明确部署只改 `.env` 开关，不应要求重装镜像。

### 3. 环境变量开关与启动日志
`SEMANTIC_COMMAND_ENABLED` 取真值 `true`/`1`（大小写不敏感）启用语义，其余情况（含未设置、`false`、空串）一律子串，不做任意字符串容错。工厂完成装配后以既有 logger（`logging.getLogger("file-bridge")`）输出 INFO：
- 子串：`Command matcher initialized: substring`
- 语义：`Command matcher initialized: semantic (model=BAAI/bge-small-zh-v1.5, threshold=0.8)`
开关开启但模型下载/加载失败时异常向上抛出终止进程，**绝不静默回退**——否则开关失去意义且故障被隐藏。

### 4. bge 短文本两侧原文嵌入，不拼接指令前缀
bge-small-zh 不是 E5 架构，无 query/passage 前缀训练约定；命令短语与用户输入都是极短文本，属对称匹配（近义判定）而非非对称检索，两侧直接以归一化原文 embed，`SemanticCommandMatcher` 内部不做任何前缀拼接。向量 L2 归一化由 fastembed ONNX 后处理无条件完成（其内置模型图已完成池化，输出直接做 L2 normalize；`TextEmbedding` 无 normalization 开关），点积等价余弦；矩阵点积取跨短语全局最大值，`>= 0.8` 命中（先验阈值，以 smoke 标定）。推理经 `asyncio.to_thread` 执行，避免阻塞事件循环；启动期短语 embedding 为一次性批量同步计算。

### 5. 归一化函数定义在 base.py，由 CommandHandler 在匹配前调用
richText 合并文本含 `<imgN>` 与换行，属噪声。`normalize_command_text()` 定义于 `base.py`：正则去 `<imgN>`、`" ".join(text.split())` 折叠空白并 strip。CommandHandler 提取/合并文本后调用它，结果为空直接视为无命中（语义模式省去一次推理），再把干净文本传给 matcher；归一化只作用于匹配输入副本。两个 matcher 因此都不感知 richText 细节、也不重复归一化，默认子串路径对既有输入（含 ` 重建索引 `、`重建索引\n<img1>`）判定结果不变。

### 6. CommandHandler 通用分发 + create_pipeline 内建分发表
CommandHandler 构造参数改为 `matcher` + `dispatch_table`（`{command_id: async callable}`），文本提取（text/richText 合并）保留在 handler，归一化调用 `base.normalize_command_text()`，执行段为 `await dispatch_table[command_id](message, raw_data, pipeline)`。默认分发表在 `create_pipeline` 内部基于其已持有的 `metadata_store` 构建（`rebuild_index` 闭包：调 `async_rebuild_index`、回复固定文案，文案与现状逐字一致）；`matcher` 是 `create_pipeline` 的注入参数。`main()` 只负责调工厂选出 matcher 并传入，不感知具体命令的接线。备选（分发表在 main 构建后整体注入）被否：会让集成测试复制 rebuild 闭包，装配知识泄漏到入口层。

### 7. 测试只分两层，分界是"是否构造真模型"
测试集以正向 marker 命名：`general`（通用默认集）与专项集 `semantic`（未来可扩展其他专项集）。pyproject 注册两个 marker 并配 `addopts = "-m general"`；`tests/conftest.py` 用 `pytest_collection_modifyitems` 钩子将"不携带任何已登记专项 marker（`SPECIAL_MARKERS = {"semantic"}`）"的测试自动标记为 general，既有 82 个测试无需手工改动；新增专项集时只需在测试上贴新 marker 并在 `SPECIAL_MARKERS` 登记，即自动退出默认集。
默认集（CI 与本地日常同一命令 `uv run pytest`，CI workflow 零改动）：
- 子串匹配器单测：目录驱动，覆盖包含命中、不包含、多命令消歧顺序。
- 语义匹配器单测：fake embedder 返回可控向量，覆盖阈值门控、跨短语取最大、短语/查询原文直传不拼前缀（空串短路在 handler 层测），不导入 fastembed。
- 归一化与 CommandHandler 单测：fake matcher（固定 id / None），验证分发命中执行、未命中不执行、空文本不调 matcher；`_merge_rich_text` 既有测试保留。
- 装配工厂单测：环境变量开关组合（未设置/false/true/TRUE/1），monkeypatch 桩掉 semantic 模块构造器，断言默认与假值得到子串匹配器、真值得到语义匹配器、日志含 substring/semantic、桩抛错时异常上传不回退；断言默认装配后 `fastembed` 不在 `sys.modules`。
- 模块组合测试（现有 `tests/test_integration.py`，不引入 integration marker，继续留在默认集）：真实 `create_pipeline` 全链路装配（真实 SQLite/文件系统/hash），经参数注入真实 `SubstringCommandMatcher`（零模型），仅 mock 外部边界（HTTP MockTransport、钉钉 SDK MagicMock、reply_text 捕获）；本次只改装配接线，5 步业务与断言保持不变。

真模型层（仅本地 `uv run pytest -m semantic`，CI 永不执行）：
- `tests/test_semantic_command_smoke.py`：测试内**直接构造** `FastEmbedEmbedder` 与 `SemanticCommandMatcher`（不经工厂、不设置 `SEMANTIC_COMMAND_ENABLED`），20 条固定样本（10 正 10 负），正例命中 ≥9/10、负例误命中 ≤1/10；模型走本地缓存，缺模型直接 fail。
- 唯一收录标准：凡是构造 `TextEmbedding` 加载真实模型权重的测试必须显式标 `semantic`；其余一律由 conftest 钩子自动归入 `general`。

### 8. Smoke 样本集与通过线
20 条固定样本：10 条正例（精确短语、带前后空格、richText 清洗后文本、口语化同义表达如"帮我重建一下索引""索引重新建一下"等真实中文说法），10 条负例（硬负例如"查询索引状态""帮我索引一下这个文件""建立文件夹""索引重建完成了吗"，及无关闲聊）。通过线：正例命中 ≥9/10 且负例误命中 ≤1/10。ONNX 推理确定，无需分数快照。不达标时仅允许调整：阈值、passage 短语表、样本集（样本必须是真实用户说法）；调整后跑 `-m semantic` 回归。DEBUG 日志记录 top 分数供调参，不作为测试断言。

## Risks / Trade-offs

- [双实现长期并存产生维护成本] → 共用同一协议、目录与归一化路径，差异仅在 match 内部；子串实现极简；语义验证成熟后可再讨论默认值切换（不在本期）。
- [推理依赖常驻镜像使镜像体积增大（数十 MB）] → 需求要求开箱可开关，这是既定代价；fastembed 不带 PyTorch，已是最轻的本地推理方案；默认运行不导入不加载，运行时开销仅在启用后发生。
- [短中文短语语义不稳定，0.8 为先验值] → 多同义短语取最大；20 条 smoke 作为阈值标定与回归抓手，调参只动阈值/短语/样本。
- [语义模式每条文本消息一次 CPU 推理（短文本约 10–30ms 量级）] → bge-small-zh 量化 ONNX（约 30MB）+ `to_thread`；空输入短路；默认关闭，仅主动启用方承担该成本。
- [容器内开启开关的首启依赖 HuggingFace 可达性，且镜像不含模型权重] → 部署时可经 HF 官方环境变量配合挂载缓存目录，或先联网完成首次下载；加载失败 fail-fast；手工模型管理/镜像预烤方向已记入 TODO，届时去除该风险。
- [默认 `pytest` 误触模型] → marker 默认排除；除 smoke 外全部测试注入假依赖或使用子串匹配器。

## Migration Plan

1. `uv add fastembed`（主依赖，更新 lock，自动进入镜像）；`.env.example` 增加 `SEMANTIC_COMMAND_ENABLED=false` 及简要注释；Dockerfile 无需改动。
2. 实现 command_matching（子串先行）、改造 CommandHandler 与 main.py 装配；此步落地后默认行为与现状一致，全部既有测试改写为注入式并保持绿。
3. 本地以代理首启下载模型，置 `SEMANTIC_COMMAND_ENABLED=true` 验证语义路径，用 smoke 样本标定阈值/短语直至通过线；部署侧改 `.env` 开关并重启即生效。
回滚：将开关置回 false 即恢复子串行为；彻底回滚需还原 CommandHandler 与装配代码、移除主依赖与环境变量；无数据迁移、无持久化状态变化。
