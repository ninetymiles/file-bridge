# Design

## Context

当前启动探测位于 `app/services/photo_review.py`，请求 `GET <base_url>/models/<urlencoded model>`，结果由 `app/main.py` 的启动 hook 用于决定是否 `disable_review()`。网关按虚拟 key 限制路由后，该路径返回 403，而 `GET /models` 与 `POST /chat/completions` 均可用。消息入口的存储预热由 `app/services/disk_warmup.py` 提供竞速逻辑，`app/handlers/message.py` 在计时器到期时发送唤醒提示并继续等待磁盘。

需求见 `specs/photo-review/spec.md` 与 `specs/storage-warmup/spec.md`；动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 用一次 `GET /models` 同时确认网关可达、凭证有效、配置模型对该 key 可用。
- 启动日志用一条 INFO/WARNING 报告呈现实际生效的 URL、模型、模型数量与模型存在性。
- 冷盘唤醒期间并发触发模型加载，缩短首次点评冷启动，同时不影响唤醒提示与磁盘等待。
- 预热 ping 只做诊断与加速，不改变点评能力开关。

**Non-Goals:**

- 不把 `/models` 列表用于运行时模型选择或动态切换。
- 不改变点评请求本身的构造、合并窗口、总时限与降级语义。
- 不修改 `disk_warmup.py` 的通用竞速协议。
- 不新增环境变量或运行时配置项。

## Decisions

### 1. 启动探测改为 `GET /models` 并做精确匹配

探测请求 `<OPENAI_BASE_URL>/models`，Bearer 认证，3 秒超时。按 OpenAI 基础返回结构解析：响应体必须是对象且 `data` 必须是数组，逐项读取 `data[].id` 作为模型标识；条目不是对象、缺少 `id` 或 `id` 不是非空字符串时跳过该项。解析出的标识与配置的 `OPENAI_MODEL` 做精确匹配（区分大小写）。

只解析 `data[].id`，不解析 LiteLLM 的 `active` / `context_window` 扩展字段，也不校验 `object`、`created`、`owned_by`：这些字段不参与可用性判断，多解析只会增加与网关实现的耦合。

放弃“先试 `/models/{model}`、失败再回退 `/models`”的方案：当前网关对逐模型路径固定 403，回退只会增加一次无效请求和分支复杂度，且无法改变路由策略。

### 2. 探测返回结构化结果，而不是布尔值

新增结果结构，至少包含：

```text
GatewayProbe
  reachable: bool          # HTTP 层是否成功
  status: int | None       # HTTP 状态码
  models: tuple[str, ...]  # 解析出的模型 id
  model_present: bool      # 配置模型是否在 models 中
  error: str | None        # 解析/网络错误摘要
  ready: bool              # reachable and model_present
```

`ready` 是唯一的能力开关依据：`main.py` 仅在 `ready` 为真时保留 reviewer，否则调用 `disable_review()`；冷盘预热也只在 `ready` 为真时触发。布尔返回值无法同时支撑报告中的模型数量、`present` 与可用样例，因此不采用。

2xx 但响应体无法解析、缺少 `data` 或 `data` 不是列表时，`reachable` 为真但 `model_present` 为假，最终 `ready` 为假并禁用点评——符合“只有 API 通且模型可用才启用”的语义。

### 3. 健康报告为单行结果日志

探测成功输出一条 INFO，失败输出一条 WARNING；请求前最多输出一条 DEBUG 尝试日志，避免 INFO 噪音。单行报告字段：

```text
url=<base_url>/models model=<model> models=<count> present=<yes|no> key=<masked>
```

失败时附加 `status` / 异常类型 / 响应体摘要；模型缺失时附加截断后的可用模型样例。完整清单只在 DEBUG 输出。API Key 复用既有 `_mask_api_key()`，不输出明文。报告只呈现进程内实际生效的配置值，不追溯 shell 环境变量与 `.env` 的来源；配置是否符合预期由运维对照报告自行判断。

### 4. 冷盘预热使用独立的有界请求

在 `app/services/photo_review.py` 增加预热函数，请求 `<base_url>/chat/completions`：

```json
{
  "model": "<OPENAI_MODEL>",
  "messages": [{"role": "user", "content": "ping"}],
  "max_tokens": 1,
  "reasoning_effort": "none"
}
```

使用独立 `httpx.AsyncClient`，建议 `connect=5s`、`read=30s`，不复用点评客户端 `read=None` 的无上限读超时。成功只记录 DEBUG；失败记录单行 WARNING（带 url、model、状态码或异常类型），永不抛出、永不修改 `ready`。

### 5. 预热由 `PipelineHandler` 以 fire-and-forget 方式触发

`PipelineHandler` 新增可选注入 `wake_warmup: Callable[[], Awaitable[None]] | None`。`_dispatch` 构造 `on_waking` 时：

1. 若 `wake_warmup` 存在，立即 `asyncio.create_task()` 启动预热（不 await）；启动 gate 的判断由注入的回调自身完成，未就绪时直接返回，`PipelineHandler` 不感知点评配置；
2. 同一个 `on_waking` 中继续 `await async_reply_text(WAKING_STORAGE_TEXT, ...)`；
3. `ensure_storage_ready` 随后照常等待磁盘探针。

预热任务加入独立集合，`begin_drain()` 时取消，避免退出时出现 “Task was destroyed” 警告。预热函数内部再维护 in-flight 标记：已有一个未完成请求时直接返回，避免冷盘期间多条消息重复加载。

不把预热放进 `disk_warmup.py`：该模块保持“探针 + 计时器 + 回调”的通用协议，业务回调由 `PipelineHandler` 组合，符合现有分层。

### 6. 启动 gate 由 `main.py` 持有

`main.py` 创建一个极小的可变 gate（例如带 `ready` 布尔字段的对象），在启动 hook 中根据 `probe.ready` 置位。`create_pipeline()` 把它闭包进 `wake_warmup` 传给 `PipelineHandler`。启动 hook 在 SDK 开始消费消息前完成，因此消息到达时 gate 已稳定。

不采用“探测成功后动态替换 pipeline 回调”的方式：可变 gate 更直观，也便于测试注入。

## 接口样本参考

解析只依赖两处结构：顶层 `data` 是数组，元素对象的 `id` 是模型标识。以下两份样本仅作对照记录，不扩大解析范围。

### OpenAI 标准返回

```json
{
  "object": "list",
  "data": [
    {
      "id": "gpt-4o",
      "object": "model",
      "created": 1715366400,
      "owned_by": "system"
    },
    {
      "id": "gpt-4o-mini",
      "object": "model",
      "created": 1721153400,
      "owned_by": "system"
    },
    {
      "id": "text-embedding-3-small",
      "object": "model",
      "created": 1705948800,
      "owned_by": "system"
    }
  ]
}
```

字段说明：`object` 固定为 `"list"`；`data[].id` 为唯一模型标识；`data[].object` 固定为 `"model"`；`data[].created` 为 Unix 秒级时间戳；`data[].owned_by` 为权属者。

### LiteLLM 扩展返回（仅参考）

```json
{
  "object": "list",
  "data": [
    {
      "id": "anthropic/claude-3-5-sonnet",
      "object": "model",
      "created": 1677610602,
      "owned_by": "litellm",
      "active": true,
      "context_window": 200000
    },
    {
      "id": "ollama/llama3.1-local",
      "object": "model",
      "created": 1721545620,
      "owned_by": "litellm",
      "active": true,
      "context_window": 131072
    },
    {
      "id": "xai/grok-2-1212",
      "object": "model",
      "created": 1677610602,
      "owned_by": "openai",
      "active": false,
      "context_window": 128000
    }
  ]
}
```

LiteLLM 在基础结构上追加三项：`id` 采用 `[provider]/[model-name]` 组合格式，供网关解析并路由到对应后端；`active`（可选）表示当前路由节点或虚拟 Key 权限下该模型是否启用；`context_window`（可选）表示上下文 Token 上限。这三项本变更都不参与判断，记录在此便于日后排障时正确解读网关返回值。

## Risks / Trade-offs

- **网关清单可能不包含可调用别名** → 按需求接受精确匹配；LiteLLM 风格下 `OPENAI_MODEL` 必须写成 `provider/model` 全名；模型缺失时 WARNING 输出可用样例，排障文档提示用 `curl <base_url>/models` 对齐 `OPENAI_MODEL`。这是“启动即校验模型”的代价。
- **LiteLLM 的 `active` 不参与判断** → 只解析基础结构时，清单中 `active=false` 的条目同样算作“存在”。若配置模型在清单中但当前 Key 无权限，探测会误判为可用，问题推迟到首次点评才暴露。这是只按 OpenAI 基础结构解析的已知代价。
- **`/models` 只能证明网关声明可用，不能证明权重已加载** → 报告使用 `present` 而非 `loaded`；实际加载由冷盘 ping 或首次点评触发。
- **预热后模型仍可能在点评到达前被卸载** → 预热只降低冷启动概率，不改变点评失败降级语义。
- **预热失败日志可能造成噪音** → 仅在冷盘唤醒时触发，且成功不输出 INFO；失败为单行 WARNING，频率与冷盘唤醒次数一致。
- **2xx 但清单不可解析会禁用点评** → 这是“模型可用性无法核实”的有意选择，避免在配置未知时误启用。

## Migration Plan

- 无数据迁移、无新增配置项；更新代码后重启进程即生效。
- 回滚时恢复逐模型探测即可；`.env` 与 `OPENAI_*` 变量无需调整。
- 部署后检查启动日志中的单行健康报告，确认 URL、模型与 `present=yes` 符合预期配置。

## Open Questions

无。
