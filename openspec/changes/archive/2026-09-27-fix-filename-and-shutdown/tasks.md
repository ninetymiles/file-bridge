## 1. 文件名截断修正

- [x] 1.1 将 `lib/file_storage.py` 的时间戳截断 `[:18]` 改为 `[:19]` 并更新上方注释为 `YYYYMMDD_HHMMSS_fff`；更新 `tests/test_file_storage.py` 两处期望值（`test_generate_saved_filename` → `[Alice]_20260924_153045_123.pdf`，`test_save_file_directory_structure_and_collision` → `[Bob]_20260924_153045_123.txt`），运行 `uv run pytest tests/test_file_storage.py` 确认 4 个用例全部通过

## 2. 停机死代码与等待收敛

- [x] 2.1 修改 `lib/runner.py`：删除 `stop()` 步骤 1 整段（runner.py:106-112 的 `client.stop()` try/except），原步骤 2 的 runner task 等待 timeout 由 5.0 改为 1.0、超时日志由 WARNING 改为 INFO 并改写为"任务未在 1s 内结束、将随进程退出抛弃"的陈述性文案；删除 `request_stop()` 中对 SDK 的 getattr 段（runner.py:173-179），**保留**对自身 `self._stop_event` 的设置（180-181）；同步更新 `stop()` docstring（删步骤 1、重编号、去旧变更路径引用），运行 `uv run pytest` 确认单测全绿（注：test_runner.py 三个用例断言旧死行为 client.stop 被调用，按新 spec 契约同步改写为 assert_not_awaited + runner_task.cancelled，42 passed）
- [x] 2.2 Live 验证 SIGINT：`uv run python -m app.main` 后台启动连接成功后，发送 SIGINT 并计时，确认总停机耗时小于 2 秒、exit code 为 0，日志中无 `has no attribute 'stop'`、无 WARNING 级 "Timeout" 文案、无未捕获堆栈；Live 验证 SIGTERM：同流程发 `kill -TERM`，确认 exit code 0 且日志路径与 SIGINT 一致（实测两信号停机耗时均 1.104s，exit 0；CLOSE 1000 正常；SDK 自身 `[start] network exception` 为已知保留噪音）
- [x] 2.3 检查两次 live 日志，确认无 `Task was destroyed but it is pending` 新增噪音（如出现则对照 5 秒旧路径是否同样存在，确认非本次回归后记录于任务备注）（实测两份日志均 0 条；Python 3.14 对无异常 pending 任务收尾静默）

## 3. 规范与全量回归

- [x] 3.1 确认 `specs/lifecycle-management/spec.md` 两个 MODIFIED 需求头（信号拦截与优雅停机、BotService 异步生命周期协议）与主 spec 完全一致，运行 `openspec validate fix-filename-and-shutdown` 通过
- [x] 3.2 运行 `uv run pytest` 全量回归，确认全部通过（修复前基线为 40 passed / 2 failed，修复后目标为 42 passed / 0 failed），并确认无残留对 SDK `stop()`/`_stop_event` 的调用（实测 42 passed / 0 failed；源码检索无残留，仅过期 .pyc 缓存命中）
