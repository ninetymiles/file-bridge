# Tasks

## 1. 脚手架与配置样例

- [x] 1.1 新建空的 `script/__init__.py`，验证 `uv run python -c "import script"` 退出码为 0
- [x] 1.2 在 `.env.example` 追加 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL` 及注释（说明地址已带 `/v1`、模型名以存在为准），验证 `grep -c '^OPENAI_' .env.example` 输出 3

## 2. 配置解析（无环境耦合）

- [x] 2.1 在 `app/services/photo_review.py` 实现 `ReviewConfig`（frozen dataclass）、`ReviewConfigError` 与 `ReviewConfig.from_env(env: Mapping[str, str])`，三个变量必需、空字符串视为缺失，验证 `uv run pytest tests/test_photo_review.py -k config` 全绿
- [x] 2.2 补齐配置用例：齐全、缺单项、空值、`--model` 覆盖语义，全部通过字面量 dict 传参，验证 `grep -c 'setenv\|monkeypatch' tests/test_photo_review.py` 输出 0

## 3. 图片预处理

- [x] 3.1 实现 `_encode_image()`：EXIF 方向校正、`thumbnail((1024,1024))`、转 RGB、JPEG q85、base64 data URI，验证用例覆盖 4032x3024->1024x768、3024x4032->768x1024、800x600 不放大、Orientation=6 方向校正、RGBA PNG 输出无 alpha 的 JPEG
- [x] 3.2 不可解码文件（文本伪装成 .jpg）返回无点评且不发起请求，验证 MockTransport 计数器为 0

## 4. Vision 请求与结果解析

- [x] 4.1 实现 `PhotoReviewer.review()` 的请求构造：`{base_url}/chat/completions`、Bearer 认证、user 消息同时含 `DEFAULT_REVIEW_PROMPT` 与 `data:image/jpeg;base64,` 载荷，验证 MockTransport 内断言 URL、认证头与请求体均成立
- [x] 4.2 实现结果解析：取 `choices[0].message.content` 并去除首尾空白；空字符串、仅空白、缺 `content` 均视为无点评。验证对应用例全绿
- [x] 4.3 实现失败降级：连接异常、500、非 JSON 响应、`choices` 缺失或为空一律返回 `None` 且不抛异常；日志不包含 API Key。验证 5 条降级用例全绿

## 5. CLI 适配层

- [x] 5.1 实现 `script/review.py`：`build_parser()`（位置参数 + `--model`）、`main(argv) -> int`（入口 `dotenv.load_dotenv()`、装配 `ReviewConfig`、`asyncio.run`）、退出码 0/1/2，验证 `uv run python -m script.review` 无参时退出码为 2
- [x] 5.2 补齐 CLI 子进程用例（构造干净 `env=`，不改当前进程 `os.environ`）：缺 `OPENAI_API_KEY` 时 stderr 含变量名且退出码 2、路径不存在时退出码 1、成功时 stdout 恰好是点评文本且退出码 0、`--model` 覆盖环境值，验证这些用例全绿
- [x] 5.3 用 `tmp_path` 验证无文件副作用：运行前后目录内文件集合与图片 mtime 不变，验证对应用例全绿
- [x] 5.4 新增 `docs/photo-review.md`：环境变量说明、`uv run python -m script.review <path>` 用法、退出码表、失败降级说明，验证文档里的命令按原样可执行（缺配置时应以退出码 2 提示变量名）

## 6. 集成验证

- [x] 6.1 运行 `uv run pytest` 全绿，且 `uv run pytest -m semantic` 不被本变更影响（不新增 `semantic` 用例）
- [x] 6.2 在本地 `.env` 配好真实网关后手工执行 `uv run python -m script.review <一张照片>`，确认输出为含"美学分析 + 夸赞"的中文点评，且原图未被修改
