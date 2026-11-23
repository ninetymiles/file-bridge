# photo-review-cli Specification

## Purpose

定义照片点评命令行入口的对外契约：以单个图片路径作为输入，从环境变量（含 `.env`）装配网关配置，调用点评服务并把结果输出到标准输出或标准错误，并以约定退出码区分"成功""点评失败""用法或配置错误"，同时保证运行过程不在文件系统留下痕迹。

## Requirements

### Requirement: 命令行调用形态

命令 SHALL 接受恰好一个位置参数——待点评图片的文件路径，并 SHALL 支持 `--model` 选项覆盖模型名，使本地调试无需改动 `.env`。命令 MUST 可通过 `python -m script.review <path>` 从仓库根目录调用。

#### Scenario: 传入图片路径正常执行

- **WHEN** 在仓库根目录执行 `python -m script.review photo.jpg` 且配置齐备
- **THEN** 命令完成一次点评请求并把点评文本写到标准输出，退出码为 0

#### Scenario: 缺少位置参数

- **WHEN** 执行命令时未提供图片路径
- **THEN** 命令打印用法提示到标准错误，退出码为 2，且不发起任何网络请求

#### Scenario: 命令行模型名覆盖环境变量

- **WHEN** 环境中设置 `OPENAI_MODEL=a`，执行时传入 `--model b`
- **THEN** 点评请求使用模型 `b`

### Requirement: 配置来源与缺失处理

命令 SHALL 在入口处加载仓库根目录的 `.env`，并从环境变量读取 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。三者均 SHALL 为必需项，命令 MUST NOT 为缺失项提供硬编码默认值。任何一项缺失时，命令 SHALL 打印指出缺失变量名的错误信息到标准错误并以非零退出码结束，且 MUST NOT 发起点评请求。

#### Scenario: 从 .env 读取完整配置

- **WHEN** `.env` 中定义了三个 `OPENAI_*` 变量，执行时未额外传参
- **THEN** 命令使用 `.env` 中的值构造点评服务

#### Scenario: 缺少必需配置项

- **WHEN** 环境与 `.env` 均未提供 `OPENAI_API_KEY`
- **THEN** 命令在标准错误中指出缺少 `OPENAI_API_KEY`，以非零退出码结束，且不发起请求

#### Scenario: 不提供模型名默认值

- **WHEN** 环境与 `.env` 均未提供 `OPENAI_MODEL`，且命令未传 `--model`
- **THEN** 命令以配置错误结束，而不是回退到任一内置模型名

### Requirement: 输出与退出码

命令 SHALL 在点评成功时向标准输出打印点评文本并以 0 退出；在点评失败（服务返回无点评）时向标准错误打印可读原因并以 1 退出；在用法或配置错误时以 2 退出。成功输出 MUST 只包含点评文本本身，不附加日志、进度或标题。

#### Scenario: 成功时输出点评文本

- **WHEN** 服务返回一段点评文本
- **THEN** 标准输出恰好是该文本（含结尾换行），退出码为 0

#### Scenario: 点评失败时退出码为 1

- **WHEN** 服务因网关错误返回无点评
- **THEN** 标准错误包含失败原因说明，标准输出为空，退出码为 1

#### Scenario: 图片路径不存在

- **WHEN** 传入的路径不存在或不是常规文件
- **THEN** 命令以退出码 1 结束，标准错误说明文件不可读

### Requirement: 运行过程不产生文件副作用

命令 SHALL 在内存中完成图片解码、缩放与编码，MUST NOT 修改输入图片，MUST NOT 在输出目录或临时目录写入中间文件。

#### Scenario: 运行后原图与目录不变

- **WHEN** 命令对一张照片成功完成点评
- **THEN** 该照片的内容未改变，其所在目录除原有文件外没有新增文件
