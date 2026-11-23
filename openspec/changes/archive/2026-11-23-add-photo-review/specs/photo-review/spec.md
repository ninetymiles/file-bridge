# Spec Delta

## Purpose

定义照片视觉点评服务的行为边界：把本地照片预处理成可发送的图片载荷，通过 OpenAI 兼容的 vision 接口获取美学点评文本，并在任何失败情形下降级为"无点评"，使调用方（当前为 CLI，后续为消息处理链）永远不会因点评失败而中断主流程。

## ADDED Requirements

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
