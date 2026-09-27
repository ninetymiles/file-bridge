## Context

现状(详见 proposal.md — Why):`lib/config.py` 82 行,运行时唯一消费者为 `app/main.py`;`define_options()` 纯转发;`AppConfig` 仅字段打包;`dotenv.load_dotenv()` 双处调用;`client_id`/`client_secret` 双重 env 回退;CLI 命名下划线/减号混用且 `notify_*` 存在双格式别名。

约束:在途变更 `support-group-chat-messages`(0/12 未动工)已规划在 `lib/config.py` 的 `AppConfig` 上新增 `log_level` 字段,本变更须先行落地,并同步修订该变更 artifacts 中的落点表述,避免其按旧路径实施时失效。

## Goals / Non-Goals

**Goals:**

- 消除入口处的无意义封装层:`lib/config.py` 模块、`define_options()`、`AppConfig`。
- CLI 参数命名统一为减号分隔,删除下划线别名。
- 消除冗余:双重 env 回退收敛为一处,`load_dotenv()` 收敛为一处。
- 保持解析行为契约不变:命令行 > 环境变量(含 .env)优先级、`OUTPUT_DIR`/`NOTIFY_*` 的 env 回退、缺失凭证时 `parser.error` 报错退出。
- 测试保持行为断言不变,仅迁移 import 路径并补充减号命名用例。

**Non-Goals:**

- 不实现 `LOG_LEVEL`(归 `support-group-chat-messages`)。
- 不重构 `setup_logger()`/`create_pipeline()`(前者已有归属,后者具有真实组装职责)。
- 不动 `BotService`/`MetadataStore`/`FileDownloader` 的封装(均有 spec 依据或为深模块设计,探索结论见变更讨论)。
- 不改环境变量名、默认值与校验时机。

## Decisions

1. **解析逻辑内联为 `app/main.py` 内的单个模块级函数(`parse_config`),而非散入 `main()` 函数体。**
   - 备选:完全内联进 `main()` — 测试将只能通过子进程驱动,7 个既有行为用例全部报废。
   - 保留一个模块级函数是测试可达性的最小代价,不构成"层"(无独立文件、无独立抽象)。
2. **删除 `AppConfig`,解析结果直接使用 `argparse.Namespace`。**
   - `main()` 内仅 5 处字段访问(`config.client_id` 等),Namespace 字段访问方式完全一致。
   - 备选:保留 dataclass 换取类型标注 — 字段少、生命周期短(仅 `main()` 局部),收益不抵实体成本。
3. **CLI 改名不留兼容别名:删除 `--client_id`/`--client_secret`/`--notify_conversation_id`/`--notify_user_id`,argparse 对旧形式直接报 unrecognized arguments(fail-fast)。**
   - 备选:保留旧名作隐藏别名 — 拒绝向后兼容垫片,双命名正是本次要消除的混乱。
   - 环境变量主路径(README/docker-compose/`.env.example` 均只引用 env)不受影响,实际破坏面极小。
4. **env 回退仅在 `add_argument(default=os.getenv(...))` 一处。**
   - 语义等价:未传参时 default 即 env 值;`parse_config` 内的二次 `or os.getenv(...)` 属冗余防御,删除。`CLIENT_ID`/`CLIENT_SECRET` 缺失校验保留在解析边界(`parser.error`),符合"系统边界严格校验、内部 fail fast"。
5. **`dotenv.load_dotenv()` 仅保留 `app/main.py` 模块级一处调用,位于解析函数之前。**
   - 删除 `lib/config.py` 中的模块级调用随文件一并消失;import 顺序天然满足(load 在模块导入时执行,解析在 `main()` 运行时执行)。
6. **交叉变更修订仅限文本落点:`support-group-chat-messages` 的 proposal/design/tasks 中"`lib/config.py` 的 `AppConfig` 新增 `log_level`"改写为"`app/main.py` 的解析函数返回的 Namespace 新增 `log_level` 字段",其需求范围与任务编号不变。**

## Risks / Trade-offs

- [以 CLI 传参的调用方破坏] → env 主路径零影响;argparse 报错信息明确指出未识别参数;在 proposal 中标注 BREAKING。
- [`tests/test_config.py` 改为 import `app.main`,引入 `dingtalk_stream` 等模块级依赖] → `.venv` 已含全部依赖,测试环境一致;`app/main.py` 模块级无连接副作用(仅 `main()` 运行时连接),import 安全。
- [delta 归档时遗漏细节] → MODIFIED 需求块按规则复制全文后仅改参数命名,archive 整体替换无信息丢失。
