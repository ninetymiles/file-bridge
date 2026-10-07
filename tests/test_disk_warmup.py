"""Unit tests for app.services.disk_warmup."""

import time

import pytest

from app.services.disk_warmup import ensure_storage_ready


@pytest.mark.asyncio
async def test_fast_probe_returns_silently():
    calls = []

    async def on_waking():
        calls.append("waking")

    await ensure_storage_ready(lambda: None, on_waking, delay=0.05)

    assert calls == []


@pytest.mark.asyncio
async def test_slow_probe_notices_once_then_still_waits_for_probe():
    events = []

    def probe():
        time.sleep(0.2)
        events.append("probe_done")

    async def on_waking():
        events.append("waking")

    await ensure_storage_ready(probe, on_waking, delay=0.05)

    # Notice fired exactly once, and the call returned only after the probe
    # had actually completed.
    assert events == ["waking", "probe_done"]


@pytest.mark.asyncio
async def test_probe_exception_propagates_on_fast_path():
    async def on_waking():
        raise AssertionError("fast path must not send the wake notice")

    def probe():
        raise OSError("volume unreachable")

    with pytest.raises(OSError, match="volume unreachable"):
        await ensure_storage_ready(probe, on_waking, delay=0.05)


@pytest.mark.asyncio
async def test_probe_exception_after_timeout_still_propagates():
    events = []

    def probe():
        time.sleep(0.2)
        raise OSError("volume unreachable")

    async def on_waking():
        events.append("waking")

    with pytest.raises(OSError, match="volume unreachable"):
        await ensure_storage_ready(probe, on_waking, delay=0.05)

    assert events == ["waking"]


@pytest.mark.asyncio
async def test_event_loop_not_blocked_during_probe():
    # The probe blocks in a worker thread far longer than the delay; the
    # timer must still expire on time instead of after the probe.
    fired_at = []

    def probe():
        time.sleep(0.5)

    async def on_waking():
        fired_at.append(time.monotonic())

    start = time.monotonic()
    await ensure_storage_ready(probe, on_waking, delay=0.05)

    assert fired_at[0] - start < 0.3
