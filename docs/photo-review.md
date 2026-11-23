# 照片点评 CLI

用 OpenAI 兼容的 vision 模型为一照片生成"美学分析 + 夸赞"。CLI 只是一层薄适配，真正的实现在 `app/services/photo_review.py`，后续会被消息处理链直接复用。

## 前置配置

在仓库根目录的 `.env` 中提供三个变量（可参考 `.env.example`）：

| 变量 | 说明 |
|---|---|
| `OPENAI_BASE_URL` | OpenAI 兼容网关地址，**必须已经带 `/v1`**；客户端只会在其后追加 `/chat/completions` |
| `OPENAI_API_KEY` | 网关的 API Key（LiteLLM 通常要求真实 key） |
| `OPENAI_MODEL` | 模型别名，必须与 LiteLLM 中注册的名字完全一致，可能是 `qwen3.5:9b`，也可能是带前缀的 `ollama/qwen3.5:9b` |

三项均为必需，缺任何一项命令都会直接报错退出，不会回退到内置默认值。查看网关实际暴露的模型名：

```shell
curl -H "Authorization: Bearer $OPENAI_API_KEY" "$OPENAI_BASE_URL/models"
```

## 用法

```shell
uv run python -m script.review <图片路径>
```

临时换模型（优先级高于 `OPENAI_MODEL`）：

```shell
uv run python -m script.review --model ollama/qwen3.5:9b ./photo.jpg
```

成功时标准输出只包含点评文本本身，方便直接重定向或管道：

```shell
uv run python -m script.review ./photo.jpg > review.txt
```

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 点评成功，点评文本已写入标准输出 |
| `1` | 点评失败（网关错误、模型无返回、图片不可读）或图片路径不存在；原因写入标准错误 |
| `2` | 用法错误（缺少图片路径）或配置缺失；不会发起任何请求 |

## 处理细节

- 图片会按 EXIF 方向校正，等比缩放到宽高均不超过 1024 像素，再转成 JPEG（质量 85）以 data URI 发送。不裁切、不放大。
- 点评要求：同时覆盖美学与摄影技术、以及对照片、景色、模特和拍摄者的夸赞，但必须融合成一段连贯文字。字数要求放在提示词末尾并带自查指令，只给一个上限（100 字），实测输出约 100–130 字且偶有超出；同时给两个数字（如"100 字左右、最多 120"）会让模型偏向较大的那个，输出涨到 140–170 字。
- 请求固定携带 `reasoning_effort: "none"`：点评属于娱乐用途，本地部署下响应速度优先，因此不让模型先内部推理（实测输出 token 约减少 4 倍）。
- 全过程在内存中完成，不写临时文件，也不修改原图。
- 点评失败只降级为"没有点评"，服务的调用方不会收到异常——这是为消息链路接入准备的行为。

## 排障

| 现象 | 常见原因 |
|---|---|
| 退出码 2，提示 `OPENAI_MODEL` 等缺失 | `.env` 未配置，或变量名拼写不一致 |
| 退出码 1，网关返回 404 | `OPENAI_MODEL` 与 LiteLLM 注册名不一致 |
| 退出码 1，网关返回 401 | `OPENAI_API_KEY` 不正确 |
| 退出码 1，提示图片不可读 | 路径错误，或文件格式不受 Pillow 支持（如 HEIC） |
| 长时间无输出后退出码 1 | 网关或上游模型超时；CLI 本身不设请求超时，请查网关日志 |
| 报 `ConnectError` 或域名解析失败，但网关其实正常 | shell 里已导出 `OPENAI_BASE_URL` 等变量，它的优先级高于 `.env`（`load_dotenv()` 不覆盖已有变量）；用 `env -u OPENAI_BASE_URL -u OPENAI_API_KEY -u OPENAI_MODEL uv run python -m script.review <path>` 让 `.env` 生效，或直接 `unset` 后重试 |
