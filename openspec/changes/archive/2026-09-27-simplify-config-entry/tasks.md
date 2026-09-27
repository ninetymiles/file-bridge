## 1. 内联参数解析

- [x] 1.1 将 `lib/config.py` 的解析逻辑内联为 `app/main.py` 内的单个模块级函数 `parse_config(args=None)`(返回 `argparse.Namespace`):CLI 参数统一减号命名(`--client-id`、`--client-secret`、`--output-dir`、`--notify-conversation-id`、`--notify-user-id`),env 回退仅保留 `add_argument(default=os.getenv(...))` 一处,保留缺失凭证时 `parser.error` 报错;删除 `define_options()`,`main()` 改为直接调用 `parse_config`,确认 `dotenv.load_dotenv()` 仅在 `app/main.py` 一处调用,运行 `uv run python -m app.main` 验证无凭证时报错退出、有 `.env` 时正常启动后 Ctrl-C 退出
- [x] 1.2 删除 `lib/config.py`,全局检索确认无残留 `lib.config`/`AppConfig`/`define_options` 引用(仅剩 tests 迁移由 2.1 处理),运行 `uv run pytest` 确认除 test_config 外其余测试不受影响

## 2. 测试迁移

- [x] 2.1 将 `tests/test_config.py` 的 import 由 `lib.config` 迁移至 `app.main`,保持 7 个既有用例的行为断言不变(仅 `test_default_output_dir` 中 `DEFAULT_OUTPUT_DIR` 断言改为字面量 `./output`),运行 `uv run pytest tests/test_config.py` 验证全部通过
- [x] 2.2 新增减号命名 CLI 用例:`parse_config(["--client-id", "id", "--client-secret", "secret"])` 覆盖环境变量,`--notify-conversation-id`/`--notify-user-id` 同理;运行 `uv run pytest tests/test_config.py` 验证通过

## 3. 规范与交叉变更修订

- [x] 3.1 确认本变更 `specs/bot-config/spec.md` 的 MODIFIED 需求块与 `openspec/specs/bot-config/spec.md` 中"凭证解析与配置回退"需求头完全一致且仅参数命名差异,运行 `openspec validate simplify-config-entry` 通过
- [x] 3.2 修订 `openspec/changes/support-group-chat-messages/` 的 proposal.md、design.md、tasks.md 1.1 中 `lib/config.py`/`AppConfig` 落点表述为 `app/main.py` 解析函数与 Namespace,需求范围与任务编号不变,人工核对三处文本一致

## 4. 回归验证

- [x] 4.1 运行 `uv run pytest` 全量回归通过;`uv run uvicorn main:app` 启动方式当前不适用(app 尚未暴露),以 `uv run python -m app.main` 作为启动验证基线,确认日志正常输出且 Ctrl-C 优雅退出
