# Spec Delta

## ADDED Requirements

### Requirement: 可选配置解析

服务 SHALL 提供可选的配置解析入口，当三个 `OPENAI_*` 变量（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`）均非空白时返回完整配置；任一变量缺失或为空白时返回"未配置"，MUST NOT 抛出异常，也 MUST NOT 发起任何网络请求。既有的必需配置解析入口 SHALL 保持"缺失即抛错"的语义不变。

#### Scenario: 三项配置齐全

- **WHEN** 传入的映射包含非空白的 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 与 `OPENAI_MODEL`
- **THEN** 可选解析返回完整配置，字段值与传入值一致（基础地址去除末尾斜杠）

#### Scenario: 任一配置缺失

- **WHEN** 传入的映射缺少 `OPENAI_API_KEY`，或该变量为空字符串
- **THEN** 可选解析返回"未配置"，不抛出异常，且不发起任何网络请求

#### Scenario: 必需解析入口行为不变

- **WHEN** 以缺失配置的映射调用必需的配置解析入口
- **THEN** 该入口仍然抛出配置错误并指出缺失变量名，命令行的退出码语义不受影响

### Requirement: 启动可用性探测

系统 SHALL 在服务启动阶段、开始接收消息之前探测点评网关与目标模型：向 `<OPENAI_BASE_URL>/models/<模型名>` 发起 `GET` 请求，模型名 MUST 进行 URL 编码，请求 MUST 携带 Bearer 认证并受 3 秒超时约束。响应为 2xx 时 SHALL 记录 INFO 并启用点评；非 2xx、超时或网络异常时 SHALL 记录 WARNING 并在本次进程内禁用点评，后续照片消息 MUST NOT 再发起点评请求。探测 MUST NOT 加载模型，也 MUST NOT 改变任何保存结果。

#### Scenario: 探测成功启用点评

- **WHEN** 网关对 `GET /models/<编码后的模型名>` 返回 200
- **THEN** 系统记录一条包含模型名的 INFO 日志，本次进程内照片回复可以包含点评

#### Scenario: 模型名不存在

- **WHEN** 网关对探测请求返回 404
- **THEN** 系统记录一条包含状态码的 WARNING 日志，本次进程内禁用点评，照片回复与未配置点评时完全一致

#### Scenario: 探测超时或网关不可达

- **WHEN** 探测请求在 3 秒内未得到响应，或连接直接失败
- **THEN** 系统记录 WARNING 并禁用点评，启动流程继续，消息处理不受影响

#### Scenario: 模型名中的特殊字符被编码

- **WHEN** 配置的模型名为 `qwen3.5:9b`
- **THEN** 探测请求路径中的模型名为 `qwen3.5%3A9b`，而不是直接拼接原始冒号

### Requirement: 点评请求总时限

消息链路发起的每一批点评 SHALL 受 60 秒总墙钟时限约束，该时限覆盖整批请求，而非为每张图片各自计时。到达总时限时，系统 SHALL 停止等待尚未完成的点评、取消对应请求并记录 WARNING；已经完成的点评 SHALL 按既有消息形态正常使用。建立连接的超时 SHALL 独立设置且不超过 5 秒，MUST NOT 替代总时限。

#### Scenario: 点评在总时限内完成

- **WHEN** 单张照片的点评请求在 1 秒内返回有效文本
- **THEN** 请求正常完成，不触发总时限相关的取消或 WARNING

#### Scenario: 请求超过总时限

- **WHEN** 一批点评在 60 秒后仍未全部完成
- **THEN** 系统取消未完成的请求并记录 WARNING，未完成的点评不出现在任何回复中，且不再补发消息

#### Scenario: 群聊多图共享一个总时限

- **WHEN** 一批图片中部分点评在 60 秒内完成、部分仍挂起
- **THEN** 已完成的点评照常参与回复，挂起的请求在总时限到达时被取消，而不是每张图片各获得 60 秒

#### Scenario: 网关不接受连接

- **WHEN** 点评网关的地址无法建立 TCP 连接
- **THEN** 该批请求在建连超时（不超过 5 秒）内失败并按"无点评"处理，不需要等到 60 秒总时限
