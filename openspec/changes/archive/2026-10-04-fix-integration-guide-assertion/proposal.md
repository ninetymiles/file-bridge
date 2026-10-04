# Fix integration guidance assertion flakiness

## Why

`tests/test_integration.py::test_end_to_end_file_and_rebuild_index_pipeline`（general 默认集、CI 均执行）在全量运行时偶发失败，失败点是其第 6 步断言：

```python
assert "• " in replies[4][0] and "保存" in replies[4][0]
```

未命中引导回复由 `build_guide_reply()` 按三维（前缀 × 外壳 × 每能力措辞 × 结尾）用 `random.choice` 现场组合。第四项"自动落盘存储"能力有 6 个等价措辞（`app/handlers/message.py` 的 `CAPABILITY_VARIANTS` 第 4 组），其中 2 个不含"保存"二字（"将接收到的文件自动存档到服务器"、"把所有接收内容自动存到服务器"）。`random` 每进程按 OS 熵播种，因此该断言以约 2/6 概率跨会话偶发失败：单独跑该测试或固定 RNG 状态下通过，全量运行时结果不确定。

## 契约分析

- 断言对象是 mock 的 `pipeline.reply_text` 捕获的**真实对外回复消息**，不是诊断日志，因此不属于"将日志作为功能断言"。
- 但违反"契约至上（验证 What 而非 How）"：message-pipeline spec 对未命中引导的契约是"回复一条引导，能力清单以条目形式列出四项能力，文件/视频限定单聊"，承诺的是**结构与能力类别**，并未承诺某次随机组合中出现"保存"这个具体词。把一次随机抽样的字面结果当稳定契约，属于把实现细节（How）误当行为（What），并引入非确定性。
- 引导组合器的措辞正确性已有确定性单测覆盖：`tests/test_command_handler.py` 用 `monkeypatch random.choice -> seq[0]` 固定抽样后验证组合结构（`reply.count("• ") == len(CAPABILITY_VARIANTS)`）与维度顺序。
- 该 integration 测试本身不多余：它是全仓库唯一用真实 `create_pipeline` + 真实 SQLite + 真实文件系统（仅 mock 外部 HTTP 与发送）的模块组合测试，且第 4 步的"图+命令双 PRIMARY 合并为一条回复"、贯穿全程的 `len(replies) == N` 发送次数断言，单测均无法替代。问题仅在第 6 步这一句断言的写法，不涉及测试整体。

## What Changes

- 修改 `tests/test_integration.py` 第 6 步断言：删除对随机措辞字面词 `"保存"` 的依赖，改为断言稳定的**结构契约**——恰好新增一条回复，且引导包含四项能力条目（`replies[4][0].count("• ") == 4`）。
- 不修改任何生产代码：`build_guide_reply()` 的随机组合行为与 spec 一致，保持不变。
- 不改动该测试其余步骤：第 2/3/7 步等处对**稳定**文案（"文件已存在，请勿重复发送"、"索引重建完成，清理元数据 X 条…"）的断言是 spec 锁定的用户可见信息要素且非随机，属正当契约，予以保留。
- 不拆分这个 11 步长流程（属可选的结构优化，超出本次修复范围）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 —— 仅修正测试断言以匹配既有 spec 契约，产品行为与规范均不变，`skip_specs: true`。）

## Impact

- 仅 `tests/test_integration.py` 一处（第 6 步一行断言）。
- 不涉及生产代码、外部 API、依赖或数据迁移。
- 修复后该测试结果不再依赖 RNG 播种状态，全量/单跑、任意执行顺序结果一致。
