# Tasks

## 1. 启动探测改为模型清单

- [x] 1.1 在 `app/services/photo_review.py` 新增探测结果结构与 `/models` 地址构造，按 OpenAI 基础结构解析 `data[].id`（跳过非对象条目、缺少 `id` 或 `id` 非字符串的条目），按配置模型精确匹配，无法解析时返回“模型不可用”；用单元测试覆盖标准样本命中、模型缺失、空列表、非法 JSON、`data` 非数组与条目缺少 `id`
- [x] 1.2 重写 `probe_gateway`：请求 `GET <base_url>/models`，返回结构化结果，移除 `sources` 参数与 `_format_sources()`，成功输出单行 INFO 健康报告，失败输出单行 WARNING，完整模型清单仅 DEBUG；验证报告包含 url、model、models 数量、present 与 Key 掩码，且不出现密钥明文
- [x] 1.3 更新 `tests/test_photo_review.py` 的探测用例，断言请求路径为 `/v1/models`、模型存在才返回 ready、模型缺失/非 2xx/连接异常均不 ready；运行 `uv run pytest tests/test_photo_review.py -k probe` 全绿

## 2. 启动装配

- [x] 2.1 启动 hook 改为按探测结果的 `ready` 决定是否 `disable_review()`，并将同一 `ready` 写入供冷盘预热读取的 gate；验证探测失败时 reviewer 为 `None`、成功时保持启用
- [x] 2.2 更新 `docs/photo-review.md` 的探测说明与排障表，写明 `GET /models`、模型必须出现在清单中、403 路由限制与单行健康报告字段；按文档执行一次启动并确认日志与描述一致

## 3. 冷盘唤醒预热 ping

- [x] 3.1 在 `app/services/photo_review.py` 实现预热请求：`POST <base_url>/chat/completions`，文本 `ping`、`max_tokens=1`、`reasoning_effort=none`、独立有界超时，成功仅 DEBUG、失败仅单行 WARNING 且永不抛出；单元测试断言请求体、超时与失败不改变任何状态
- [x] 3.2 在 `app/handlers/message.py` 的 `PipelineHandler` 新增可选 `wake_warmup` 注入，在 `on_waking` 中先 fire-and-forget 启动预热再发送唤醒提示，预热任务加入集合并在 `begin_drain()` / `cancel_tasks()` 时取消；验证唤醒提示不被预热延迟
- [x] 3.3 在 `app/main.py` 组合 gate 与 `wake_warmup`，仅当启动健康检测 `ready` 时触发；用集成测试覆盖冷盘触发、热盘不触发、健康检测失败不触发
- [x] 3.4 为预热函数增加 in-flight 去重，保证同一冷盘唤醒期间至多一个未完成请求；用并发测试断言重复调用不会叠加请求
- [x] 3.5 在 `tests/test_integration.py` 补充冷盘顺序断言：唤醒提示先于或并发于预热请求、磁盘探针继续完成、预热失败不影响最终回复；运行 `uv run pytest tests/test_integration.py tests/test_pipeline.py tests/test_photo_review.py` 全绿
- [x] 3.6 更新 `docs/photo-review.md` 的冷启动说明与 `docs/storage.md` 的预热章节，写明 ping 只用于提前加载、失败仅诊断、不参与点评开关；按文档检查一次冷盘日志

## 4. 变更验证

- [x] 4.1 运行 `uv run pytest`，确认全部单元与集成测试通过
- [x] 4.2 运行 `openspec validate "photo-review-models-probe-warmup" --strict`，确认规格与场景无告警
- [x] 4.3 用本地或测试网关启动应用，确认启动日志出现单行健康报告、模型缺失时点评被禁用、冷盘唤醒时出现预热诊断日志

## Workflow follow-up

- 在项目评审要求满足后归档该变更。
- 归档后检查 `openspec/specs/photo-review/spec.md` 与 `openspec/specs/storage-warmup/spec.md` 已合并新要求。
