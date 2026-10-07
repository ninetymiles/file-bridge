"""Storage warmup race: a blocking probe in a worker thread vs. a notice timer.

Cold network storage (e.g. a sleeping NAS) blocks on the first disk I/O for
tens of seconds inside a synchronous syscall. This module runs that probe off
the event loop while a timer stays on it, so callers can notify the user on
time and still wait for the disk to come back.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable


async def ensure_storage_ready(
    probe: Callable[[], None],
    on_waking: Callable[[], Awaitable[None]],
    delay: float = 3.0,
) -> None:
    """Race the storage probe against the wake-notice timer.

    The probe runs via asyncio.to_thread so a cold disk never blocks the
    event loop. If the probe finishes within ``delay`` seconds, the timer is
    cancelled and the call returns silently. If the timer expires first,
    ``on_waking`` is awaited (the caller sends its notice) and the probe is
    then awaited to completion. Probe exceptions propagate to the caller.

    wait_for is not usable here: its timeout cancels the awaited object, and
    to_thread cannot cancel the underlying thread, which would leave the
    probe running with an unretrieved exception.
    """
    probe_task = asyncio.create_task(asyncio.to_thread(probe))
    timer_task = asyncio.create_task(asyncio.sleep(delay))
    finished, _ = await asyncio.wait(
        {probe_task, timer_task}, return_when=asyncio.FIRST_COMPLETED
    )

    if timer_task not in finished:
        # Fast path: storage was ready. Settle the cancelled timer so it
        # cannot outlive the caller and trip "task destroyed" warnings.
        timer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await timer_task
    elif not probe_task.done():
        await on_waking()

    await probe_task
