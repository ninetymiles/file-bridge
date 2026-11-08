"""Unit tests for DailyReportScheduler."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.daily_report_scheduler import DailyReportScheduler
from app.services.metadata_store import IndexStatistics


def _empty_stats():
    return IndexStatistics(
        total_files=0, total_users=0, typed_counts={}, null_saved_paths=(), daily=()
    )


def _delta_stats():
    return IndexStatistics(
        total_files=5,
        total_users=2,
        typed_counts={"picture": 3, "video": 1, "file": 1},
        null_saved_paths=(),
        daily=(),
    )


def _total_stats():
    return IndexStatistics(
        total_files=156,
        total_users=12,
        typed_counts={"picture": 100, "video": 50, "file": 6},
        null_saved_paths=(),
        daily=(),
    )


def _make_scheduler(last_check=None):
    store = MagicMock()
    store.async_rebuild_index = AsyncMock(return_value=(0, 0))
    store.async_count_new_since = AsyncMock(return_value=_empty_stats())
    store.async_get_index_statistics = AsyncMock(return_value=_total_stats())
    notifier = MagicMock()
    notifier.send_to_staff = AsyncMock(return_value=True)
    scheduler = DailyReportScheduler(
        metadata_store=store, notifier=notifier, last_check=last_check
    )
    return scheduler, store, notifier


def test_next_daily_check_before_nine():
    now = datetime(2026, 11, 8, 8, 0, 0)
    nxt = DailyReportScheduler._next_daily_check(now)
    assert nxt == datetime(2026, 11, 8, 9, 0, 0)


def test_next_daily_check_after_nine():
    now = datetime(2026, 11, 8, 10, 0, 0)
    nxt = DailyReportScheduler._next_daily_check(now)
    assert nxt == datetime(2026, 11, 9, 9, 0, 0)


def test_next_daily_check_exactly_nine_rolls_to_tomorrow():
    now = datetime(2026, 11, 8, 9, 0, 0)
    nxt = DailyReportScheduler._next_daily_check(now)
    assert nxt == datetime(2026, 11, 9, 9, 0, 0)


@pytest.mark.asyncio
async def test_run_daily_check_with_new_files_sends_report():
    scheduler, store, notifier = _make_scheduler(
        last_check=datetime(2026, 11, 7, 9, 0, 0)
    )
    store.async_count_new_since = AsyncMock(return_value=_delta_stats())

    await scheduler.run_daily_check()

    store.async_rebuild_index.assert_awaited_once()
    store.async_count_new_since.assert_awaited_once_with("2026-11-07 09:00:00")
    notifier.send_to_staff.assert_awaited_once()
    args = notifier.send_to_staff.call_args
    assert args.args[0] == "📊 每日缓存统计"
    assert "自2026-11-07 09:00 新增" in args.args[1]
    assert "当前索引总量" in args.args[1]


@pytest.mark.asyncio
async def test_run_daily_check_no_new_files_skips_report():
    scheduler, store, notifier = _make_scheduler(
        last_check=datetime(2026, 11, 7, 9, 0, 0)
    )

    await scheduler.run_daily_check()

    store.async_rebuild_index.assert_awaited_once()
    notifier.send_to_staff.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_daily_check_without_notifier_no_error():
    store = MagicMock()
    store.async_rebuild_index = AsyncMock(return_value=(0, 0))
    store.async_count_new_since = AsyncMock(return_value=_delta_stats())
    store.async_get_index_statistics = AsyncMock(return_value=_total_stats())
    scheduler = DailyReportScheduler(
        metadata_store=store, notifier=None, last_check=datetime(2026, 11, 7, 9, 0, 0)
    )

    await scheduler.run_daily_check()

    store.async_rebuild_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_daily_check_updates_last_check():
    scheduler, store, _notifier = _make_scheduler(
        last_check=datetime(2026, 11, 7, 9, 0, 0)
    )
    store.async_count_new_since = AsyncMock(return_value=_delta_stats())

    before = datetime.now()
    await scheduler.run_daily_check()
    after = datetime.now()

    assert before <= scheduler.last_check <= after


@pytest.mark.asyncio
async def test_scheduler_loop_triggers_at_nine():
    scheduler, store, notifier = _make_scheduler()
    store.async_count_new_since = AsyncMock(return_value=_delta_stats())

    # First datetime.now() (loop's `now`) is before 9 so next_run is today 9:00;
    # all subsequent calls are past 9 so the reach-or-exceed check fires.
    first_now = datetime(2026, 11, 8, 8, 59, 0)
    later_now = datetime(2026, 11, 8, 9, 0, 1)
    now_values = iter([first_now])

    def fake_now():
        try:
            return next(now_values)
        except StopIteration:
            return later_now

    sleep_calls = {"count": 0}

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError

    with patch("app.services.daily_report_scheduler.asyncio.sleep", fake_sleep), \
         patch("app.services.daily_report_scheduler.datetime") as mock_dt:
        mock_dt.now.side_effect = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        with pytest.raises(asyncio.CancelledError):
            await scheduler._scheduler_loop()

    store.async_rebuild_index.assert_awaited_once()
    notifier.send_to_staff.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_loop_does_not_trigger_before_nine():
    scheduler, store, notifier = _make_scheduler()

    # now is 8:00, next check is 9:00, sleep capped at 3600.
    fixed_now = datetime(2026, 11, 8, 8, 0, 0)
    sleep_calls = {"count": 0}

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        raise asyncio.CancelledError

    with patch("app.services.daily_report_scheduler.asyncio.sleep", fake_sleep), \
         patch("app.services.daily_report_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        with pytest.raises(asyncio.CancelledError):
            await scheduler._scheduler_loop()

    store.async_rebuild_index.assert_not_awaited()
    notifier.send_to_staff.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_stop_idempotent():
    scheduler, _store, _notifier = _make_scheduler()

    scheduler.start()
    assert scheduler._task is not None
    first_task = scheduler._task
    scheduler.start()
    assert scheduler._task is first_task

    scheduler.stop()
    # Yield to the loop so the cancellation propagates and the task settles.
    try:
        await asyncio.wait_for(first_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    assert first_task.done()
