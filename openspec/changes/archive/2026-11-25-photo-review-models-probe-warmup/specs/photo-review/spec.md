# Spec Delta

## REMOVED Requirements

### Requirement: 启动可用性探测

**Reason**: 逐模型探测路径 `GET /models/<model>` 在网关虚拟 key 路由限制下固定返回 403，导致 API 可用时点评仍被禁用；该路径也无法再用于验证模型是否存在。

**Migration**: 由新增的“启动模型清单探测”要求替代。部署无需修改 `OPENAI_*` 配置，重启应用后自动改用 `GET /models`。

## ADDED Requirements

### Requirement: 启动模型清单探测

系统 SHALL 在服务启动阶段、开始接收消息之前探测点评网关与目标模型：向 `<OPENAI_BASE_URL>/models` 发起 `GET` 请求，携带 Bearer 认证并受 3 秒超时约束。系统 SHALL 按 OpenAI 基础返回结构解析响应：读取顶层 `data` 数组内各元素的 `id` 作为模型标识，并以精确匹配（区分大小写）判断配置的 `OPENAI_MODEL` 是否在清单中。仅当响应为 2xx 且配置模型出现在清单中时，系统 SHALL 启用本次进程内的点评能力；非 2xx、超时、网络异常、响应体无法解析出模型清单，或配置模型不在清单中时，系统 SHALL 禁用本次进程内的点评能力。探测 MUST NOT 加载模型，也 MUST NOT 改变任何保存结果。

#### Scenario: 探测成功且模型可用时启用点评

- **WHEN** 网关对 `GET /models` 返回 200，且清单包含配置的 `OPENAI_MODEL`
- **THEN** 系统记录一条健康报告 INFO 日志，本次进程内照片回复可以包含点评

#### Scenario: 网关可达但配置模型不在清单中

- **WHEN** 网关对 `GET /models` 返回 200，但清单不包含配置的 `OPENAI_MODEL`
- **THEN** 系统记录一条包含 `present=no` 的 WARNING 日志，本次进程内禁用点评，照片回复与未配置点评时完全一致

#### Scenario: 模型清单无法解析

- **WHEN** 网关对 `GET /models` 返回 200，但响应体不是合法 JSON，或缺少 `data` 数组、`data` 不是数组
- **THEN** 系统记录 WARNING，视为模型可用性无法核实，并在本次进程内禁用点评

#### Scenario: 网关不可达或返回非 2xx

- **WHEN** 探测请求在 3 秒内未得到响应、连接失败，或网关返回 401、403、404、500 等非 2xx 状态
- **THEN** 系统记录一条包含状态码或异常类型的 WARNING 日志，并在本次进程内禁用点评，启动流程继续，消息处理不受影响

### Requirement: 启动健康报告

启动健康检测 SHALL 输出单行日志报告，包含请求地址、配置模型、可用模型数量、配置模型是否在清单中与 API Key 掩码。成功时 SHALL 使用 INFO 级别；失败时 SHALL 使用 WARNING 级别。报告 MUST NOT 输出 API Key 明文，完整模型清单 MAY 仅在 DEBUG 级别输出。

#### Scenario: 健康检测通过时输出完整单行报告

- **WHEN** `GET /models` 返回 200 且配置模型在清单中
- **THEN** INFO 报告单行包含请求地址、配置模型、模型数量、`present=yes` 与 API Key 掩码

#### Scenario: 模型缺失时报告可用样例

- **WHEN** `GET /models` 返回 200 但清单不包含配置模型
- **THEN** WARNING 报告包含 `present=no` 与截断后的可用模型样例，便于直接修正 `OPENAI_MODEL`

#### Scenario: 报告不泄漏密钥

- **WHEN** 健康检测成功或失败
- **THEN** 输出的单行报告只包含 API Key 掩码，不包含密钥明文
