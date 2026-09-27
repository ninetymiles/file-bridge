## Why

`tests/test_lifecycle_notifier.py` 中多个功能用例以诊断日志（`logger.debug/warning.assert_called()`、WARNING 日志文本匹配）作为功能正确性的断言依据，违反项目 `AGENTS.local.md` "禁止将诊断日志作为功能测试的断言"与"契约至上：测试验证系统做了什么而非怎么记录"的准则。日志文本是易变的实现细节，断言它会让合理的日志重构误判为功能回归；功能结果（返回值、其余目标是否仍被发送）才是可观察契约。

## What Changes

- 移除 `tests/test_lifecycle_notifier.py` 中 5 处诊断日志断言（静默跳过用例的 `debug.assert_called`、异常隔离/异常不崩溃/超时用例的 `warning.assert_called`、空卡片实例用例的 WARNING 文本匹配），断言收敛为返回值与发送交互等可观察行为。
- 同步移除这些用例中仅为日志断言而构造的 `MagicMock()` logger 参数。
- 调整 bot-config "生命周期通知目标配置"需求中"单个目标发送失败不阻断其余目标"场景：THEN 只描述可观察行为（继续向其余目标发送、整体流程不中断），不再将"记录 WARNING 日志"作为契约措辞。实现中的日志记录行为保持不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `bot-config`: "生命周期通知目标配置"需求的"单个目标发送失败不阻断其余目标"场景措辞收敛，去除诊断日志层面的契约表述。

## Impact

- 测试：仅 `tests/test_lifecycle_notifier.py`，用例数量不变，预期断言更稳定。
- 规范：`dual-notify-targets-and-staff-id` 尚未 archive，本变更与其 MODIFIED 同一需求；**归档顺序必须为 dual-notify-targets-and-staff-id 在先、本变更在后**，本变更 delta 按 dual-notify 合并后的需求全文书写。
- 生产代码：无改动。
- 不触碰其它测试文件：`test_pipeline.py`、`test_file_downloader.py`、`test_config.py`、`test_drain.py` 中的 caplog 断言分别由 `observability`/`bot-config`/`lifecycle-management` 规范明确要求（日志策略与脱敏即契约），不在本变更范围。
