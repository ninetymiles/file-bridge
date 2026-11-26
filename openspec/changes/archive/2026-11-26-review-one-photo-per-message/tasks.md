# Tasks

## 1. 选择与点评启动

- [x] 1.1 将 `_handle_rich_text` 循环内的 `batch.add` 改为“仅在尚无点评任务时对保存成功的图片起跑”，复用 `_ReviewBatch.__bool__` 写成 `if not batch: batch.add(index, path)`；验证：新增用例让 3 张图片全部保存成功，断言 `len(reviewer.calls) == 1` 且只点评第 1 张图片的落盘路径
- [x] 1.2 确认重复图片被跳过且不消耗点评机会：验证：新增用例让第 1 张 `async_is_duplicate` 返回真、第 2 张保存成功，断言点评路径为第 2 张，且回复中出现「图2：」
- [x] 1.3 确认全部图片重复或保存失败时不发起点评：验证：新增用例让 3 张图片全部重复，断言 `reviewer.calls == []` 且 `len(replies) == 1`

## 2. 图号渲染

- [x] 2.1 为 `_format_reviews` 增加“是否多图消息”入参，`_handle_rich_text` 以 `len(picture_segments) > 1` 传入；多图消息渲染 `图{N}：{文本}`，单图消息直接输出文本；验证：新增用例断言多图消息回复含「图2：」且不含「图1：」「图3：」，单图消息回复不含「图1：」

## 3. 既有测试契约改写

- [x] 3.1 改写 `test_group_reviews_merge_into_one_labelled_message` 为“只点评第 1 张且只产生一条带图号的点评”，断言点评请求次数为 1；验证：`uv run pytest tests/test_media_review_reply.py -k merge_into_one_labelled` 通过
- [x] 3.2 改写 `test_group_partial_failure_omits_the_failed_image` 为“第 1 张保存成功的图片点评失败时本条消息无点评、不换图、只发一条回复”，删除“图1/图3 并存”的旧断言；验证：该用例通过且 `len(replies) == 1`
- [x] 3.3 更新 `test_group_reviews_start_before_later_downloads_finish` 的断言为“只点评第 1 张，且点评在后续下载完成前已起跑”；验证：该用例通过且 `len(reviewer.calls) == 1`

## 4. 回归验证

- [x] 4.1 运行完整测试套件；验证：`uv run pytest` 全绿
- [x] 4.2 校验 OpenSpec 变更；验证：`openspec validate review-one-photo-per-message --strict` 通过

## Workflow follow-up

- Archive the change after the project's review requirements are satisfied.
- Sync the delta specs into `openspec/specs/message-pipeline/spec.md` and `openspec/specs/photo-review/spec.md` during archive.
