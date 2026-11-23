# Design

## Context

- 现有照片路径：`app/handlers/message.py` 的 `_process_one_image` 在落盘后调用 `extract_media_metadata(saved_path, msgtype)`，把摘要行拼进 `ReplyIntent`。该函数是同步纯函数，失败返回 `None`，注释明确"never raises"。
- 现有 HTTP 惯例：`FileDownloader` 在构造时接受 `http_client: Optional[httpx.AsyncClient]`，未注入时自行创建；日志用 `file-bridge.<sub>` 命名。
- 现有配置惯例：`app/main.py` 只在 `main()` 中调用 `dotenv.load_dotenv()`，`parse_config` 通过 `os.getenv` 作为 argparse 默认值；`tests/test_config.py::test_importing_app_main_does_not_load_dotenv` 用子进程保证"导入无副作用"。
- 网关形态：业务前置 LiteLLM，对外暴露 `<host>/v1` 的 OpenAI 兼容地址，背后是 ollama 上的 vision 模型。因此无需拼接 `/v1`，不做 base URL 归一化；单次请求阻塞等待可接受。
- 依赖 `httpx`、`pillow`、`python-dotenv` 已在 `pyproject.toml`，无新增。

## Goals / Non-Goals

**Goals:**

- 服务模块可以被未来的 handler 直接调用：异步、显式配置、可注入 HTTP 客户端、失败只降级不抛错。
- CLI 只是输入输出适配：解析参数、装配配置、调用服务、打印结果与退出码，不含业务逻辑。
- 全部测试离线可跑：不连网关、不加载模型、不读写进程环境变量。

**Non-Goals:**

- 本次不接入 `app/handlers/message.py`，不改动消息回复内容。
- 不做流式输出、缓存、批处理、图片编辑或打分持久化。
- 不提供 `pyproject.toml` 的 console_scripts 入口（项目 `package = false`，不安装包）。

## Decisions

### D1. 代码位置：服务进 `app/services/`，CLI 进 `script/`

服务放 `app/services/photo_review.py`，CLI 放 `script/review.py`，并新增空的 `script/__init__.py`。

理由：用户已明确后续要合并进消息链路，服务必须在 `app/` 内才能被干净导入。`script/` 加 `__init__.py` 是为了 `python -m script.review` 有稳定的包路径——直接 `python script/review.py` 时 `sys.path[0]` 是 `script/`，`import app` 会失败。

被否掉的方案：单文件脚本（第二阶段重写）；在 `app/main.py` 的 argparse 里加子命令（把长期驻留的 bot 入口和一次性 CLI 混在一起，且 `parse_config` 强制要求钉钉凭证）。

### D2. 服务形状：`PhotoReviewer` + 一个公开方法

```
PhotoReviewer(
    base_url: str,          # 已带 /v1
    api_key: str,
    model: str,
    http_client: httpx.AsyncClient | None = None,
    logger: logging.Logger | None = None,
)
async def review(self, image_path: str) -> str | None
```

- `review()` 是唯一公开行为入口，内部拆 `_encode_image()`（同步、纯）和 `_request()`。
- 返回 `str | None` 而不是结果对象：调用方只关心"有没有点评"，失败原因由服务自身日志承担，避免状态字段。
- 服务不覆盖注入客户端的超时策略：超时属于客户端创建者的决策，CLI 创建时用 `timeout=None`（LiteLLM 侧有上游超时），未来 handler 接入时显式传短超时。
- 同步的 Pillow 解码在 CLI 场景无影响；handler 接入时事件循环会被阻塞几十毫秒，届时用 `asyncio.to_thread` 包一层即可，不影响当前接口。

### D3. 配置装配：`ReviewConfig.from_env(env)` 接受显式映射

```python
@dataclass(frozen=True)
class ReviewConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ReviewConfig": ...
```

- 三个变量全部必需，**没有默认值**。模型名由 LiteLLM 注册决定（可能是 `qwen3.5:9b`，也可能是带 provider 前缀的别名），任何内置默认值都会变成隐式错误。
- 缺失时抛 `ReviewConfigError`，消息里带缺失变量名。
- `env` 必须是显式参数，签名里**不写** `= os.environ` 默认值——这一点是测试隔离的关键（见 D7）。
- `.env` 的加载只发生在 `script/review.py` 的 `main()` 里（`dotenv.load_dotenv()` 后再读 `os.environ`），与 `app/main.py` 完全同构；服务模块导入时既不读也不写环境。

### D4. 图片预处理

`Image.open` → `ImageOps.exif_transpose` → `img.thumbnail((1024, 1024), LANCZOS)` → `convert("RGB")`（带 alpha 的先合成到白色背景）→ `save(BytesIO, "JPEG", quality=85)` → base64 data URI。GIF 等多帧格式只取第一帧。

- 用 `thumbnail` 而不是 `resize`：它只缩不放，天然满足"小图不放大"，且保持纵横比。
- 不裁切：构图本身是点评对象，裁成正方形会改变被评价的内容。
- 全程内存（`BytesIO`），不落临时文件，满足 CLI 的"无文件副作用"。
- 不可解码的文件（含 HEIC/RAW 这类 Pillow 无内置解码器的格式）直接判为无点评，且**不发起请求**。

### D5. 提示词：固定常量，两段式输出

模块常量 `DEFAULT_REVIEW_PROMPT`，要求模型输出"美学分析（构图/光影/色彩/瞬间/主体）+ 夸赞"两部分。不开放 `--prompt`：固定提示词才能让 CLI 输出可预期、也可作为后续 handler 的稳定基线；要定制再提需求，加参数本身不难。

测试**不断言模型输出的具体格式**（那是模型的自由），只断言提示词文本被原样放进请求体。

### D6. 失败降级：一个 try 包住全部，分层记录

`review()` 整体 `try/except Exception`，返回 `None`：

| 失败点 | 日志级别 | 是否发请求 |
|---|---|---|
| 文件不存在 / 无法解码 | `debug`（CLI 侧另行报错） | 否 |
| 连接失败、超时 | `warning` | 已尝试 |
| 非 2xx | `warning`，带状态码与响应体前 200 字符 | 已尝试 |
| 响应非 JSON / 缺 `choices` / content 为空 | `warning` | 已尝试 |

日志里不出现 API Key、也不打完整 base URL 的查询串（与 `mask_access_token` 的克制一致）。

### D7. 测试策略：不碰 `os.environ`、不碰网络

这是本设计最需要说清的部分。三层隔离，逐层收窄：

```
第 1 层  配置       ReviewConfig.from_env({...})      传 dict，进程环境完全不参与
第 2 层  网络       httpx.MockTransport               请求不出进程，响应由测试构造
第 3 层  图片       tmp_path + PIL 现场合成            不依赖 fixtures 里的真实照片
```

**为什么不用 `monkeypatch.setenv`**：`setenv` 改的是进程级 `os.environ`，同一进程内后续用例、以及 `app/main.py` 的 `parse_config` 都会看到残留值，用例越多越容易互相干扰。项目里已有这类写法，但新用例不再沿用。

**配置怎么测**：`from_env` 的入参是 `Mapping`，所以直接传字面量 dict：

- 齐全 → 断言三个字段值；
- 缺任一项 → `pytest.raises(ReviewConfigError)` 且消息含变量名；
- 值为空字符串 → 同样视为缺失（`.env` 里写了 `OPENAI_MODEL=` 的常见失误）；
- 覆盖语义 → 合并 `{**env, "OPENAI_MODEL": "b"}` 即可表达，无需真的改环境。

**CLI 的端到端怎么测**：唯一需要"环境变量"的地方是 `python -m script.review` 这个进程边界。用 `subprocess.run(..., env=clean_env, cwd=project_root)`，即**为新子进程构造一份干净环境**，而不是改当前进程的 `os.environ`。`tests/test_config.py::test_importing_app_main_does_not_load_dotenv` 已是这个模式的先例，可以照抄（`env` 里剔除 `OPENAI_*`，必要时塞入假配置，`PATH`/`PYTHONPATH` 保留）。

**请求怎么断言**：`httpx.MockTransport(handler)` 注入 `AsyncClient(transport=..., base_url=...)`，在 handler 里检查 `request.url.path == "/v1/chat/completions"`、`request.headers["authorization"]`、`json.loads(request.content)`；同时把 data URI 取出来用 PIL 解码，断言宽高与格式——这样"预处理规格"是通过真实请求体验证的，而不是测私有函数。

**降级怎么断言**：handler 依次返回 500 / HTML / 空 `choices` / 缺 `content`，断言 `await reviewer.review(path) is None`；对"不可解码文件"额外在 handler 里累加计数器，断言计数为 0，证明请求确实没发出。

**导入副作用怎么测**：子进程里 `import app.services.photo_review` 前后比对 `os.environ` 快照（只读环境，不写），以及在没有任何 `OPENAI_*` 的干净环境里构造 `PhotoReviewer` 并成功跑一次 mock 请求。

**异步测试**：`pytest-asyncio` 已在 dev 依赖，`asyncio_mode` 未配置，因此用例显式加 `@pytest.mark.asyncio`（与 `tests/test_command_handler.py` 一致）。`tests/conftest.py` 已经把 `-m general` 改写成"只排除 `semantic`"的钩子，所以新增用例不需要声明标记，也不会被默认运行筛掉；`strict_markers = true` 意味着不能随手引入未注册的标记。

### D8. CLI 结构

```
script/review.py
  DEFAULT_TIMEOUT = None
  EXIT_OK = 0 / EXIT_REVIEW_FAILED = 1 / EXIT_USAGE = 2
  build_parser() -> argparse.ArgumentParser      # path 位置参数, --model
  main(argv: list[str] | None = None) -> int
      dotenv.load_dotenv()
      args = parser.parse_args(argv)              # 缺位置参数 -> 2
      校验路径存在且是文件                        # 否则 stderr + 1
      try: ReviewConfig.from_env(os.environ)      # 缺失 -> stderr + 2
      asyncio.run(_run(config, path))             # 0 或 1
```

`main()` 返回退出码而不是 `sys.exit`，便于未来用子进程测试或直接调用；`__main__` 块里 `raise SystemExit(main())`。成功时 `print(text)`，失败时 `print(reason, file=sys.stderr)`，reason 是固定的可操作提示（"点评失败：网关未返回可用结果，请检查 OPENAI_BASE_URL 与模型名"），细节在服务日志里。

### D9. `.env.example` 增量

```
# OpenAI-compatible vision gateway (LiteLLM proxy in front of ollama)
# Base URL must already include /v1.
OPENAI_BASE_URL=http://localhost:4000/v1
OPENAI_API_KEY=sk-...
# Model alias exactly as registered in LiteLLM (e.g. qwen3.5:9b or ollama/qwen3.5:9b)
OPENAI_MODEL=qwen3.5:9b
```

## Risks / Trade-offs

- [阻塞式解码在 handler 场景占用事件循环] → 本次只走 CLI；接入时用 `asyncio.to_thread` 包住 `_encode_image`。
- [`timeout=None` 遇到挂死的网关会一直等] → CLI 可 Ctrl-C；后续 handler 接入必须显式传入短超时，并在 design 里列为前置条件。
- [原图极大时解码内存峰值高] → 后续可加像素上限（如 `Image.MAX_IMAGE_PIXELS` 收紧），当前不做。
- [模型输出长度不可控，未来钉钉消息有长度限制] → 本次不截断；接入时在 reply 拼接处做长度保护。
- [HEIC/RAW 静默降级，用户以为模型没看出内容] → CLI 的 stderr 会给出统一失败提示；若后续需要，可单独区分"格式不支持"。
- [JPEG q85 压缩可能损失细节点评依据] → 1024 长边下影响有限，必要时调质量或改 PNG。
- [提示词是否稳定产出两段内容取决于模型] → 不写测试断言格式，只保证提示词送达。

## Migration Plan

纯新增：部署只需补齐 `.env` 三个变量，无需改动任何现有代码路径。回滚 = 删除 `app/services/photo_review.py`、`script/` 新增文件、`tests/test_photo_review.py`，并回退 `.env.example`。

## Open Questions

- LiteLLM 中该模型的对外别名到底是 `qwen3.5:9b` 还是带 provider 前缀，部署时以 `curl <base>/v1/models` 为准；只影响 `.env` 取值，不影响代码。
- 未来 handler 接入时，点评是同步拼进当前回复还是"先回 EXIF、再补发一条点评"，取决于实测延迟与钉钉消息约束；本变更不预设。
