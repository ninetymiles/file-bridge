"""Daily cache-increment report scheduler.

Runs a background asyncio loop that fires once per day at 09:00 local time.
The loop caps each sleep at :data:`MAX_SLEEP_SECONDS` and uses a
"reach-or-exceed" trigger so system suspend or clock jumps never cause a
missed check or a duplicate trigger.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.services.index_report import format_daily_delta, format_index_snapshot
from app.services.lifecycle_notifier import LifecycleNotifier
from app.services.metadata_store import MetadataStore

# Max seconds between scheduler ticks. Capping at 1 hour bounds the delay
# after a system resume: the next check fires within an hour of wake-up.
MAX_SLEEP_SECONDS = 3600
DAILY_CHECK_HOUR = 9
DAILY_CHECK_MINUTE = 0


class DailyReportScheduler:
    """Schedules the daily 09:00 cache-increment check and staff report."""

    def __init__(
        self,
        metadata_store: MetadataStore,
        notifier: Optional[LifecycleNotifier] = None,
        logger: Optional[logging.Logger] = None,
        last_check: Optional[datetime] = None,
    ):
        self.metadata_store = metadata_store
        self.notifier = notifier
        self.logger = logger or logging.getLogger("file-bridge.daily-report")
        # Baseline lives in memory only; a restart re-baselines to now.
        self.last_check: datetime = last_check or datetime.now()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Launch the scheduler loop as a background task (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._scheduler_loop())

    def stop(self) -> None:
        """Cancel the scheduler loop task (idempotent)."""
        if self._task and not self._task.done():
            self._task.cancel()

    @staticmethod
    def _next_daily_check(now: datetime) -> datetime:
        """Return the next 09:00 strictly after ``now``."""
        candidate = now.replace(
            hour=DAILY_CHECK_HOUR, minute=DAILY_CHECK_MINUTE, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    async def run_daily_check(self) -> None:
        """Run one check: clean index, count new files, report only if any.

        Order matters: rebuild first so records whose files were deleted
        offline are removed before we count "new" files, and the reported
        delta reflects only still-present cached files.
        """
        await self.metadata_store.async_rebuild_index()

        previous_check = self.last_check
        last_check_str = previous_check.strftime("%Y-%m-%d %H:%M:%S")
        delta_stats = await self.metadata_store.async_count_new_since(last_check_str)
        self.last_check = datetime.now()

        if delta_stats.total_files == 0:
            self.logger.info("Daily check: no new files since %s", last_check_str)
            return

        if not self.notifier:
            self.logger.info(
                "Daily check: %d new file(s) since %s but no notifier configured",
                delta_stats.total_files,
                last_check_str,
            )
            return

        total_stats = await self.metadata_store.async_get_index_statistics()
        content = (
            f"{format_daily_delta(delta_stats, previous_check)}\n"
            f"{format_index_snapshot(total_stats)}"
        )
        await self.notifier.send_to_staff("📊 每日缓存统计", content)
        self.logger.info(
            "Daily check: reported %d new file(s) to staff", delta_stats.total_files
        )

    async def _scheduler_loop(self) -> None:
        """Sleep-capped loop that triggers run_daily_check at each 09:00."""
        while True:
            try:
                now = datetime.now()
                next_run = self._next_daily_check(now)
                sleep_seconds = min(
                    (next_run - now).total_seconds(), MAX_SLEEP_SECONDS
                )
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)

                # Reach-or-exceed: fire once the scheduled time has passed.
                if datetime.now() >= next_run:
                    await self.run_daily_check()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # A failed check must not kill the loop; log and continue.
                self.logger.warning("Daily check iteration failed: %s", e)
