# Tasks

## 1. Spec 同步

- [x] 1.1 将 delta spec 应用到主 spec：`openspec/specs/message-pipeline/spec.md` 补充单聊 video 结构、单聊纯文本 richText 结构、@ 段位置说明；`openspec/specs/media-metadata/spec.md` 分辨率格式 `×` 改为 `x`。验证：两处主 spec 包含全部新 Scenario 且格式符号统一为 `x`
- [x] 1.2 确认实现与更新后 spec 一致（代码当前已按日志行为运行，视频分辨率输出为字母 `x`）。验证：`uv run pytest` 全量通过
- [x] 1.3 归档变更。验证：`openspec validate` 通过，主 spec 反映全部修改
