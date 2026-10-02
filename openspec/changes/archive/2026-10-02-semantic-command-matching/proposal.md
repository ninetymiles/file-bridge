## Why

当前命令匹配是硬编码子串判断（`"重建索引" in content`），命令知识、匹配方式、执行逻辑三者耦合；TODO 已规划"语义化功能调用"。本次先建立可扩展的命令匹配与分发机制：默认保留与现状行为一致的子串匹配（零风险、无新增运行期依赖），并以环境变量开关提供基于 embedding 的语义匹配，为后续命令扩展与灰度验证语义能力铺好底座，而不一次性铺开多个命令。

## What Changes

- 抽象统一的命令匹配器协议：输入归一化后的文本，输出 command id 或无命中；命令处理器只按分发表 `{command_id: 异步回调}` 执行，不内置任何具体命令知识。
- 提供两个匹配器实现：
  - **子串匹配器（默认）**：按命令目录 `{command_id: [短语...]}` 做短语包含判断，行为与现有 `"重建索引" in content` 等价，不加载任何模型。
  - **语义匹配器（开关启用）**：仅当环境变量 `SEMANTIC_COMMAND_ENABLED=true` 时才初始化 fastembed（ONNX Runtime，CPU 本地推理）加载 `BAAI/bge-small-zh-v1.5`（512 维，中文为主、兼容目录内英文短语），首次运行从 HuggingFace 下载并走官方缓存；启动时对命令短语原文一次性 embed 存入内存，用户输入原文现场 embed（bge 短文本对称匹配，两侧均不拼接指令前缀），numpy dot product 取最大相似度，不低于固定阈值 0.8 判定命中。
- 启动装配处 SHALL 以 INFO 级别明确打印当前生效的匹配器类型（substring / semantic）；启用 semantic 时模型加载失败即 fail-fast，绝不静默回退到子串匹配。
- 将现有"重建索引"迁移进命令目录与分发表；文本在送入任一匹配器前统一归一化（剥离 richText 合并产生的 `<imgN>` 占位符、折叠空白），空文本不触发匹配（语义模式下也不触发模型推理）。
- fastembed 作为**主依赖**随工程与 Docker 镜像完整安装，语义匹配模块代码始终在产物内；默认运行只是不导入、不加载模型。部署时仅需在 `.env` 将 `SEMANTIC_COMMAND_ENABLED` 置真并重启即切换为语义匹配器（首次启动仍需模型文件可用：从 HuggingFace 下载或挂载已缓存模型）。
- 测试集以正向 marker 分层：`general` 通用集（裸 `pytest`/CI 默认执行，不加载模型，未贴专项标记的测试由 conftest 钩子自动归入）与 `semantic` 专项集（`pytest -m semantic` 显式运行真模型：10 正 10 负样本，正向命中率 ≥90%、负例误命中率 ≤10%，模型不可用直接失败）。

## Capabilities

### New Capabilities

- `semantic-command`: 命令匹配机制，涵盖匹配器选择开关与启动日志、默认子串匹配器、可选的本地 embedding 语义匹配器（模型加载契约、裸文本嵌入、阈值门控）、命令目录与分发表、匹配前归一化。

### Modified Capabilities

- `message-pipeline`: 命令解析由"处理器内固定子串包含判断"改为"文本归一化后交由可配置的命令匹配器，再按 id 分发"；默认子串匹配保持现有行为。处理器链流转模型与多处理器协作行为不变。

## Impact

- 依赖：`pyproject.toml` 新增主依赖 `fastembed`（传递 onnxruntime/numpy），随 `uv sync` 安装、随 Docker 镜像（`uv sync --no-dev`）完整分发，部署侧无需额外安装步骤。已核实 Python 3.14 有对应 cp314 wheel（onnxruntime ≥1.24.1）。
- 配置：新增环境变量 `SEMANTIC_COMMAND_ENABLED`（默认关闭），同步更新 `.env.example`；模型名、阈值 0.8 为代码常量；模型下载/缓存遵循 HF 官方环境变量（`HF_TOKEN`、`HF_HUB_OFFLINE`），不新增自定义模型路径配置。
- 代码：新增 `app/services/command_matching/` 包——`base.py`（匹配器抽象基类与共享归一化）、`catalog.py`（命令目录）、`substring.py`（子串实现）、`semantic.py`（语义实现与 embedder 薄封装，模块顶层导入 fastembed）、`__init__.py`（装配工厂，仅在开关启用分支导入 semantic 模块）；修改 `app/handlers/message.py`（CommandHandler 通用分发、匹配前归一化）、`app/main.py`（按开关装配并打印匹配器类型）；Dockerfile 无需修改（主依赖自动入镜）。
- 测试：新增子串匹配器单测、语义匹配器单测（假 embedder）、装配工厂单测（开关组合与装配日志）、语义 smoke 测试；改写现有 CommandHandler 单测与端到端集成测试，默认路径不加载模型。
- 部署：镜像内含完整语义模块与依赖，开启开关即可用；容器内模型文件首次获取（HF 下载或挂载缓存）、镜像预烤模型与容器缓存卷本次不处理，手工模型管理记入 TODO 后续规划。
