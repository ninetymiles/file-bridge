## Context

本变更为纯 spec 文档同步：将 2026-10-03 线上实测日志（log1/log2/log3）中的消息结构观察补充进 `message-pipeline` 与 `media-metadata` 主 spec。现有实现行为与日志已一致，无代码变更。

## Goals / Non-Goals

- Goals：spec 消息结构样本与线上实测保持一致；视频分辨率格式表述与实现输出（字母 `x`）统一
- Non-Goals：不修改任何代码、测试或配置；不引入新需求；不改变既有处理行为

## Decisions

- 无技术决策。所有补充内容均直接取自脱敏后的线上日志样本；视频 `duration` 为字符串秒数、`videoType` 为容器类型标识，均仅作登记，不参与现有下载与元数据流程。
