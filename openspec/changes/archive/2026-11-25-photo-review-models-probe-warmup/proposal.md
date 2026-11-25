# Proposal

## Why

当前点评启动探测使用 `GET <base_url>/models/<model>`，但网关按虚拟 key 限制为 `llm_api_routes` 后，该路径固定返回 403，导致 API 实际可用时点评仍被禁用；同时冷盘唤醒期间没有提前触发模型加载，首次点评仍要承担约 9 秒的冷启动。启动日志也没有记录实际生效的地址与模型，配置是否符合预期只能靠猜。

## What Changes

- 启动健康检测改为 `GET <base_url>/models`，拉取该 key 的可用模型清单。
- 仅当请求成功且 `OPENAI_MODEL` 精确出现在清单中时启用点评；非 2xx、超时、网络异常、清单无法解析或模型不在清单中时禁用点评。
- 健康检测返回可用模型清单结构，启动日志输出单行报告，包含 URL、模型、模型数量、模型是否存在与 API Key 掩码。
- 在磁盘唤醒超时（冷盘）时，若启动健康检测已通过，则 fire-and-forget 发送一个 `max_tokens=1` 的文本 chat ping，提前触发模型加载。
- 该 ping 不参与点评启用/禁用决策：失败只输出一行 WARNING，成功仅在 DEBUG 可见；不阻塞唤醒提示与磁盘等待，并对并发 ping 做 in-flight 去重。
- 更新 `docs/photo-review.md` 与相关测试，移除对 `/models/{model}` 与模型名 URL 编码的依赖。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `photo-review`: 启动可用性探测从逐模型请求改为模型清单请求，并要求模型在清单中才启用点评；新增单行健康报告。
- `storage-warmup`: 新增冷盘唤醒期间的可选 LLM 预热 ping，明确其并发、失败降级与不参与能力开关的边界。

## Impact

- 代码：`app/services/photo_review.py`、`app/main.py`、`app/handlers/message.py`；`app/services/disk_warmup.py` 的通用竞速逻辑保持不变。
- 测试：`tests/test_photo_review.py` 的探测用例、冷盘 ping 用例，以及 `tests/test_integration.py` 的唤醒顺序用例。
- 文档：`docs/photo-review.md` 的探测与排障章节。
- 配置：不新增环境变量，继续使用 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。
