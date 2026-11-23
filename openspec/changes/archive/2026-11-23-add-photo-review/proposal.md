# Proposal

## Why

当前照片落盘后只回复文件名与 EXIF 摘要行，用户拿到的是"参数"，不是"评价"。项目后续要在同一回复里追加 AI 照片点评（美学分析 + 夸赞），但这条能力现在既没有实现，也没有一个可离线验证的入口——直接在 handler 里写死调用会让调试、回归和失败降级都难以验证。先把点评能力做成可复用的服务，再配一层极薄的 CLI 适配，就能在不碰消息链路的前提下验证模型输出、图片预处理和异常降级。

## What Changes

- 新增 `app/services/photo_review.py`：可复用的照片点评服务，负责图片预处理（EXIF 方向校正、等比缩放到 1024 长边以内、转 JPEG、base64 data URI）、向 OpenAI 兼容网关发起 vision 请求、解析回复文本；任何异常一律降级为"无点评"，不向上抛错。
- 新增 `script/review.py` 与 `script/__init__.py`：极薄 CLI，只做参数解析、环境变量装配、调用服务、打印结果与退出码，可用 `uv run python -m script.review <path>` 运行。
- 新增 `tests/test_photo_review.py`：用 `httpx.MockTransport` 与 `tmp_path` 夹具覆盖预处理、请求构造、响应解析与降级路径，不使用真实模型、不读写进程环境变量。
- 更新 `.env.example`：补充 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL` 三个变量的说明与示例值。
- 不引入新依赖：`httpx`、`pillow`、`python-dotenv` 已是项目依赖。

**非目标（Non-goals）**

- 本变更不修改 `app/handlers/message.py` 的回复内容，点评接入消息链路是后续变更。
- 不做异步/流式输出、不做点评缓存、不做多图批量点评。
- 不做 base URL 归一化：网关由 LiteLLM 代理，对外地址已带 `/v1`。

## Capabilities

### New Capabilities

- `photo-review`: 定义照片点评服务的行为边界——图片预处理规格、vision 请求形态、回复解析，以及任何失败都不中断调用方的降级语义。
- `photo-review-cli`: 定义点评命令行入口的契约——位置参数、环境变量与命令行参数的优先级、标准输出内容与退出码。

### Modified Capabilities

（无。消息链路与现有 EXIF 能力的行为均不改变，handler 接入留待后续变更。）

## Impact

- 代码：新增 `app/services/photo_review.py`、`script/__init__.py`、`script/review.py`、`tests/test_photo_review.py`。
- 配置：`.env.example` 新增 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`；本地 `.env` 需自行补齐（已被 gitignore）。
- 依赖：无新增；沿用 `httpx`、`pillow`、`python-dotenv`。
- 系统：需要可访问的 LiteLLM 网关（OpenAI 兼容，暴露 `.../v1`）及其背后的 vision 模型；缺失时 CLI 以非零退出码报错，服务本身只降级。
- 后续变更：`app/services/photo_review.py` 将被 handler 直接复用，因此其构造签名需保持"显式配置 + 可注入 httpx 客户端"。
