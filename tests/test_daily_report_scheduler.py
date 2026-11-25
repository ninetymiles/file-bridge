"""Unit tests for DailyReportScheduler."""

import asyncio
import contextlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

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


def _make_scheduler(last_check=None, clock=None, sleep=None):
    store = MagicMock()
    store.async_rebuild_index = AsyncMock(return_value=(0, 0))
    store.async_count_new_since = AsyncMock(return_value=_empty_stats())
    store.async_get_index_statistics = AsyncMock(return_value=_total_stats())
    notifier = MagicMock()
    notifier.send_to_staff = AsyncMock(return_value=True)
    scheduler = DailyReportScheduler(
        metadata_store=store,
        notifier=notifier,
        last_check=last_check,
        clock=clock,
        sleep=sleep,
    )
    return scheduler, store, notifier


class FakeClock:
    """Deterministic wall clock the scheduler reads through its injection point."""

    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleep:
    """Advance the fake clock for the first N sleeps, then block until stopped."""

    def __init__(self, clock: FakeClock, advance_steps: int = 1):
        self.clock = clock
        self.advance_steps = advance_steps
        self.calls = []
        self._block = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if len(self.calls) <= self.advance_steps:
            self.clock.advance(seconds)
            await asyncio.sleep(0)
            return
        await self._block.wait()


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition was not met before the timeout")
        await asyncio.sleep(0.005)


def _started_tasks(before: set) -> set:
    return {task for task in asyncio.all_tasks() - before if task is not asyncio.current_task()}


async def _stop_and_join(scheduler, tasks) -> None:
    scheduler.stop()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


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
async def test_scheduler_fires_at_nine():
    clock = FakeClock(datetime(2026, 11, 8, 8, 59, 0))
    sleeper = FakeSleep(clock)
    scheduler, store, notifier = _make_scheduler(clock=clock, sleep=sleeper)
    store.async_count_new_since = AsyncMock(return_value=_delta_stats())

    before = asyncio.all_tasks()
    scheduler.start()
    await asyncio.sleep(0)
    tasks = _started_tasks(before)
    try:
        await _wait_until(lambda: notifier.send_to_staff.await_count >= 1)
    finally:
        await _stop_and_join(scheduler, tasks)

    store.async_rebuild_index.assert_awaited_once()
    notifier.send_to_staff.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_does_not_fire_before_nine():
    clock = FakeClock(datetime(2026, 11, 8, 8, 0, 0))
    sleeper = FakeSleep(clock, advance_steps=0)
    scheduler, store, notifier = _make_scheduler(clock=clock, sleep=sleeper)

    before = asyncio.all_tasks()
    scheduler.start()
    await asyncio.sleep(0)
    tasks = _started_tasks(before)
    await asyncio.sleep(0.02)
    await _stop_and_join(scheduler, tasks)

    # The first sleep is capped at one hour, well short of 09:00.
    assert sleeper.calls == [3600]
    store.async_rebuild_index.assert_not_awaited()
    notifier.send_to_staff.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_and_stop_are_idempotent():
    clock = FakeClock(datetime(2026, 11, 8, 8, 0, 0))
    sleeper = FakeSleep(clock, advance_steps=0)
    scheduler, store, _notifier = _make_scheduler(clock=clock, sleep=sleeper)

    before = asyncio.all_tasks()
    scheduler.start()
    await asyncio.sleep(0)
    first_tasks = _started_tasks(before)
    assert len(first_tasks) == 1

    scheduler.start()
    await asyncio.sleep(0)
    assert _started_tasks(before) == first_tasks

    scheduler.stop()
    scheduler.stop()
    await _stop_and_join(scheduler, first_tasks)

    assert all(task.done() for task in first_tasks)
    store.async_rebuild_index.assert_not_awaited()
