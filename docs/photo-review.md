# 照片点评

用 OpenAI 兼容的 vision 模型为照片生成"美学分析 + 夸赞"。能力实现在 `app/services/photo_review.py`，机器人（钉钉消息链）直接调用，`script/review.py` 是命令行适配层。

## 前置配置

在仓库根目录的 `.env` 中提供三个变量（可参考 `.env.example`）：

| 变量 | 说明 |
|---|---|
| `OPENAI_BASE_URL` | OpenAI 兼容网关地址，**必须已经带 `/v1`**；客户端只会在其后追加 `/chat/completions` |
| `OPENAI_API_KEY` | 网关的 API Key（LiteLLM 通常要求真实 key） |
| `OPENAI_MODEL` | 模型别名，必须与 LiteLLM 中注册的名字完全一致，可能是 `qwen3.5:9b`，也可能是带前缀的 `ollama/qwen3.5:9b` |

三项均为必需，缺任何一项命令都会直接报错退出，不会回退到内置默认值。机器人则相反：三项未配齐时点评静默禁用，照片回复与未接入点评时完全一致。查看网关实际暴露的模型名：

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

## 在钉钉消息中的行为

机器人启动时会用 `GET <OPENAI_BASE_URL>/models` 探测网关（超时 3 秒），解析 OpenAI 标准返回中 `data[].id` 的模型清单，并与 `OPENAI_MODEL` 精确匹配（区分大小写）。只有响应 2xx 且清单包含该模型时才启用点评；非 2xx、超时、网络异常、清单无法解析或模型不在清单中，都会记一条 WARNING 并在本次进程内**禁用点评**，直到重启。探测只验证地址、凭证与模型名，不会加载模型。

不要用逐模型路径 `GET /models/<模型名>` 探测：当前网关按虚拟 key 限制 `llm_api_routes` 后，该路径固定返回 403。

成功时输出单行 INFO 健康报告，字段为 `url=<base_url>/models model=<模型> models=<数量> present=yes key=<掩码>`；失败时输出同级 WARNING，字段相同，并按原因附加 `status` 或异常类型，模型缺失时追加删减后的可用模型样例。完整清单只在 DEBUG 输出。

启用后，照片回复采用两段式：

| 时间点 | 发生什么 |
|---|---|
| 落盘 + EXIF 就绪 | 点评请求已在每张图片保存后启动；15 秒合并窗口从首次回复就绪时开始 |
| 15 秒内拿到点评 | 只发一条回复：文件名、EXIF、点评依次排列，点评不加前缀 |
| 15 秒后才拿到 | 先发文件名 + EXIF；点评返回后再补发一条以「照片点评：」开头的消息 |
| 点评失败或超过 60 秒 | 只发文件名 + EXIF，不补发，也不提示失败 |

- 单条消息最多产生 **2 条回复**，不会为"正在生成点评"单独发提示。
- 群聊一次发送多张图片时，点评合并成一条消息，按「图1：…」「图2：…」分段；只包含点评成功的图片，失败的不出现。
- 60 秒是整批点评的总时限（不是每张各 60 秒），到点取消未完成的请求并记 WARNING；已完成的点评照常使用。
- `video` 与 `file` 消息不点评。
- 点评在首次回复之后才发送，停机时正在进行的点评会被直接取消，不会补发。

注意：探测成功不等于模型已加载。模型被卸载后第一次点评仍可能触发约 9 秒的冷加载（实测 8.94 秒）；这段时间通常仍在 15 秒窗口内，表现为回复稍慢。

当消息处理入口的存储探针超过 3 秒（冷盘），且启动健康检测已通过时，机器人会在发送「正在唤醒存储服务」提示的同时，后台发起一次 `max_tokens=1` 的文本 ping（内容 `ping`），提前触发模型加载。该 ping 不阻塞提示与磁盘等待，也不参与点评启用决策：成功只在 DEBUG 可见，失败只记一行 WARNING；同一冷盘期间并发消息至多只有一个未完成的 ping。

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
- 点评失败只降级为"没有点评"，服务的调用方不会收到异常；消息链路的降级与两段式行为都建立在这一契约之上。

## 排障

| 现象 | 常见原因 |
|---|---|
| 启动日志 `Photo review disabled: OPENAI_* not configured` | 三项配置未配齐；照片回复仍正常，只是没有点评 |
| 启动日志 `Photo review health FAILED ... present=no` | `OPENAI_MODEL` 不在 `/models` 清单中；按日志里的 `available=` 样例修正别名，LiteLLM 下需带 `provider/` 前缀 |
| 启动日志 `Photo review health FAILED ... status=403` | 网关按虚拟 key 限制路由；确认该 key 能访问 `/models`，且不要改用逐模型路径 |
| 启动日志 `Photo review health FAILED ... error=ConnectError` | 网关地址不可达；确认 ollama/LiteLLM 已启动后重启机器人 |
| 启动日志 `Photo review warmup FAILED` | 冷盘预热 ping 失败，只影响首次点评的快慢；确认网关与模型状态后无需重启 |
| 照片回复有 EXIF 但没有点评 | 点评失败或超过 60 秒总时限，查看 `file-bridge.review` 的 WARNING |
| 点评总是晚于保存消息到达 | 点评未在 15 秒内完成，属预期的两段式行为 |
| 退出码 2，提示 `OPENAI_MODEL` 等缺失 | `.env` 未配置，或变量名拼写不一致 |
| 退出码 1，网关返回 404 | `OPENAI_MODEL` 与 LiteLLM 注册名不一致 |
| 退出码 1，网关返回 401 | `OPENAI_API_KEY` 不正确 |
| 退出码 1，提示图片不可读 | 路径错误，或文件格式不受 Pillow 支持（如 HEIC） |
| 长时间无输出后退出码 1 | 网关或上游模型超时；CLI 本身不设请求超时，请查网关日志 |
| 报 `ConnectError` 或域名解析失败，但网关其实正常 | shell 里已导出 `OPENAI_BASE_URL` 等变量，它的优先级高于 `.env`（`load_dotenv()` 不覆盖已有变量）；用 `env -u OPENAI_BASE_URL -u OPENAI_API_KEY -u OPENAI_MODEL uv run python -m script.review <path>` 让 `.env` 生效，或直接 `unset` 后重试 |
