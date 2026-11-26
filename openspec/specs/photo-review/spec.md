# photo-review Specification

## Purpose

定义照片视觉点评服务的行为边界：把本地照片预处理成可发送的图片载荷，通过 OpenAI 兼容的 vision 接口获取美学点评文本，并在任何失败情形下降级为"无点评"，使调用方（当前为 CLI，后续为消息处理链）永远不会因点评失败而中断主流程。

## Requirements

### Requirement: 图片预处理规格

服务 SHALL 在发送前对输入图片执行以下预处理：按 EXIF 方向校正旋转、等比缩放到宽和高均不超过 1024 像素、转换为 JPEG、编码为 base64 data URI。缩放 MUST NOT 裁切画面，MUST NOT 放大尺寸小于 1024 的图片。带透明通道的图片 SHALL 以不透明背景合成后输出 JPEG。

#### Scenario: 超大横图被等比缩小

- **WHEN** 输入一张 4032x3024 的横向照片
- **THEN** 发送载荷中的图片为 1024x768，纵横比与原图一致，且为 JPEG data URI

#### Scenario: 竖图按长边缩放

- **WHEN** 输入一张 3024x4032 的竖向照片
- **THEN** 发送载荷中的图片为 768x1024，长边为 1024

#### Scenario: 小图不被放大

- **WHEN** 输入一张 800x600 的照片
- **THEN** 发送载荷中的图片保持 800x600，不进行放大插值

#### Scenario: EXIF 方向被应用

- **WHEN** 输入一张带 Orientation=6（顺时针旋转 90 度）标记、像素尺寸为 4000x3000 的照片
- **THEN** 发送载荷中的图片方向已校正，像素尺寸为 768x1024

#### Scenario: 透明通道图片转换为不透明 JPEG

- **WHEN** 输入一张带 alpha 通道的 PNG 图片
- **THEN** 发送载荷中的图片为不带透明通道的 JPEG data URI

### Requirement: Vision 请求构造

服务 SHALL 向 `<OPENAI_BASE_URL>/chat/completions` 发起 POST 请求，使用 Bearer Token 认证，请求体采用 OpenAI chat completions 形态：包含配置的模型名，以及一条 user 消息，该消息同时携带中文点评提示词与上一条要求生成的图片 data URI。基础地址已由网关保证带 `/v1`，服务 MUST NOT 自行追加或重写 `/v1` 路径段。

#### Scenario: 请求地址与认证头

- **WHEN** 基础地址为 `http://gateway.local/v1`，且服务以该配置发起一次点评
- **THEN** 请求发往 `http://gateway.local/v1/chat/completions`，且请求头包含 `Authorization: Bearer <api_key>`

#### Scenario: 请求体包含图片与提示词

- **WHEN** 服务对任意一张可解析的照片发起点评
- **THEN** 请求体的 messages 中存在一条 user 消息，其内容同时包含文本提示词和以 `data:image/jpeg;base64,` 开头的图片地址

#### Scenario: 提示词要求美学分析与夸赞

- **WHEN** 服务构造点评请求
- **THEN** 提示词要求模型输出美学分析（构图、光影、色彩等技术维度）与夸赞两部分内容

### Requirement: 点评结果解析

服务 SHALL 从响应的 `choices[0].message.content` 提取点评文本，去除首尾空白后返回。当 content 去除空白后为空字符串时，服务 SHALL 视为没有点评。

#### Scenario: 正常返回点评文本

- **WHEN** 网关返回 `choices[0].message.content` 为一段点评文字（前后带换行）
- **THEN** 服务返回去除首尾空白后的点评文字

#### Scenario: 模型返回空内容

- **WHEN** 网关返回的 `choices[0].message.content` 为空字符串或只含空白
- **THEN** 服务返回无点评

### Requirement: 点评失败降级

服务 MUST NOT 向调用方抛出异常。网络错误、非 2xx 响应、响应体不是合法 JSON、`choices` 结构缺失或为空、图片无法解码或格式不受支持，SHALL 一律返回无点评，且不修改输入文件。

#### Scenario: 网关返回服务端错误

- **WHEN** 网关对点评请求返回 500 状态码
- **THEN** 服务返回无点评，不抛出异常

#### Scenario: 响应体不是合法 JSON

- **WHEN** 网关返回 200 但响应体为 HTML 错误页
- **THEN** 服务返回无点评，不抛出异常

#### Scenario: 响应缺少 choices 结构

- **WHEN** 网关返回合法 JSON 但不存在 `choices` 或 `choices` 为空数组
- **THEN** 服务返回无点评，不抛出异常

#### Scenario: 图片无法解码

- **WHEN** 输入文件不是图片或已损坏，无法被图像解码器打开
- **THEN** 服务返回无点评，不抛出异常，且不发起任何网关请求

### Requirement: 显式配置注入

服务 SHALL 仅使用构造时显式传入的配置（基础地址、API Key、模型名、超时策略、HTTP 客户端），MUST NOT 读取进程环境变量，MUST NOT 在模块导入时产生任何副作用。

#### Scenario: 进程环境缺少配置仍可构造

- **WHEN** 进程环境中没有任何 `OPENAI_*` 变量，调用方以显式参数构造服务
- **THEN** 服务构造成功，并完全依据传入参数工作

#### Scenario: 导入模块不读取环境

- **WHEN** 在未设置 `OPENAI_*` 变量的进程中导入该服务模块
- **THEN** 导入成功，且进程环境变量在导入前后保持一致

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

### Requirement: 启动模型清单探测

系统 SHALL 在服务启动阶段、开始接收消息之前探测点评网关与目标模型：向 `<OPENAI_BASE_URL>/models` 发起 `GET` 请求，携带 Bearer 认证并受 3 秒超时约束。系统 SHALL 按 OpenAI 基础返回结构解析响应：读取顶层 `data` 数组内各元素的 `id` 作为模型标识，并以精确匹配（区分大小写）判断配置的 `OPENAI_MODEL` 是否在清单中。仅当响应为 2xx 且配置模型出现在清单中时，系统 SHALL 启用本次进程内的点评能力；非 2xx、超时、网络异常、响应体无法解析出模型清单，或配置模型不在清单中时，系统 SHALL 禁用本次进程内的点评能力。探测 MUST NOT 加载模型，也 MUST NOT 改变任何保存结果。

#### Scenario: 探测成功且模型可用时启用点评

- **WHEN** 网关对 `GET /models` 返回 200，且清单包含配置的 `OPENAI_MODEL`
- **THEN** 本次进程内照片回复可以包含点评

#### Scenario: 网关可达但配置模型不在清单中

- **WHEN** 网关对 `GET /models` 返回 200，但清单不包含配置的 `OPENAI_MODEL`
- **THEN** 本次进程内禁用点评，照片回复与未配置点评时完全一致

#### Scenario: 模型清单无法解析

- **WHEN** 网关对 `GET /models` 返回 200，但响应体不是合法 JSON，或缺少 `data` 数组、`data` 不是数组
- **THEN** 视为模型可用性无法核实，并在本次进程内禁用点评

#### Scenario: 网关不可达或返回非 2xx

- **WHEN** 探测请求在 3 秒内未得到响应、连接失败，或网关返回 401、403、404、500 等非 2xx 状态
- **THEN** 本次进程内禁用点评，启动流程继续，消息处理不受影响

### Requirement: 点评请求总时限

消息链路发起的点评获取 SHALL 受 60 秒总墙钟时限约束。一条入站消息 SHALL 至多发起一次点评请求（多图消息只点评第一张保存成功的图片，不重试、不顺延），该时限自请求发起时起算。到达总时限时，系统 SHALL 停止等待并将其取消，未取得的点评 SHALL 不出现在任何回复中，且 MUST NOT 再发起新的请求。建立连接的超时 SHALL 独立设置且不超过 5 秒，MUST NOT 替代总时限。

#### Scenario: 点评在总时限内完成

- **WHEN** 单张照片的点评请求在 1 秒内返回有效文本
- **THEN** 请求正常完成，不触发总时限相关的取消

#### Scenario: 请求超过总时限

- **WHEN** 本次点评在 60 秒后仍未完成
- **THEN** 系统取消未完成的请求，未完成的点评不出现在任何回复中，且不再补发消息

#### Scenario: 群聊多图共享一个总时限

- **WHEN** 一条多图消息对第一张保存成功的图片发起点评
- **THEN** 本条消息只有一个点评请求受 60 秒总时限约束；时限到达后不发起任何替代请求，也不换用其他图片

#### Scenario: 网关不接受连接

- **WHEN** 点评网关的地址无法建立 TCP 连接
- **THEN** 该次请求在建连超时（不超过 5 秒）内失败并按"无点评"处理，本条消息不再发起新请求
