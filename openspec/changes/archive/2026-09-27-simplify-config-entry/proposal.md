## Why

`lib/config.py` 全文仅 82 行且运行时唯一消费者是 `app/main.py`,单独成层违反"单文件优先、如无必要勿增实体"的编写准则;入口处还叠加了三层无谓包装——`define_options()` 纯转发、`AppConfig` dataclass 仅做字段打包、`dotenv.load_dotenv()` 在 `lib/config.py` 与 `app/main.py` 重复调用。同时 CLI 参数命名格式混杂:凭证参数用下划线(`--client_id`/`--client_secret`),其余用减号,`notify_*` 还保留双格式别名;`client_id`/`client_secret` 存在双重环境变量回退(`add_argument` default 与 `parse_config` 内各回退一次)。本次重构先行落地,避免在途变更 `support-group-chat-messages` 规划中写死在 `lib/config.py` 的 `log_level` 落点失效。

## What Changes

- 删除 `app/main.py` 中的 `define_options()` 纯转发封装,`main()` 直接调用解析函数。
- **BREAKING** 删除 `lib/config.py`,参数解析逻辑内联到 `app/main.py`;运行时不再存在 config 模块层。
- **BREAKING** 删除 `AppConfig` dataclass,解析结果直接使用 `argparse.Namespace`(`config.client_id` 等字段访问方式不变)。
- **BREAKING** CLI 参数命名统一为减号分隔:`--client_id` → `--client-id`、`--client_secret` → `--client-secret`;删除 `--notify_conversation_id` 与 `--notify_user_id` 下划线别名,仅保留 `--notify-conversation-id`/`--notify-user-id`。
- 消除 `client_id`/`client_secret` 的双重环境变量回退,仅在 `add_argument(default=os.getenv(...))` 一处回退。
- `dotenv.load_dotenv()` 收敛为 `app/main.py` 一处调用。
- 更新 `bot-config` 规范:凭证参数的 CLI 命名改为减号格式。
- 修订在途变更 `support-group-chat-messages` 的 `proposal.md`/`design.md`/`tasks.md` 中 `lib/config.py` 相关落点表述为 `app/main.py`(仅文本落点修订,不改其需求范围)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `bot-config`: 凭证解析需求中的命令行参数命名由 `--client_id`/`--client_secret` 统一为 `--client-id`/`--client-secret`;解析优先级(命令行 > 环境变量含 .env)与缺失报错行为不变。

## Impact

- **代码**:
  - `app/main.py`:内联参数解析逻辑(约 50 行),删除 `define_options()`,`dotenv.load_dotenv()` 保留此处。
  - `lib/config.py`:整文件删除。
  - `tests/test_config.py`:import 由 `lib.config` 迁移至 `app.main`,原有 7 个用例行为断言不变;补充减号命名参数用例。
- **CLI 契约(breaking)**:以命令行方式传凭证或通知目标的调用方需改用减号命名;通过环境变量/`.env` 配置的调用方不受影响(README/docker-compose/`.env.example` 均未引用 CLI 参数形态)。
- **规范**:`openspec/specs/bot-config/spec.md` 场景中的参数命名同步更新。
- **交叉变更**:`openspec/changes/support-group-chat-messages/` 的 proposal/design/tasks 中 `lib/config.py` 落点表述修订为 `app/main.py`,其 `log_level` 需求范围不变。
- **依赖**:无新增第三方依赖。
