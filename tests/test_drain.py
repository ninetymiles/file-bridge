"""Unit tests for the shutdown drain mechanics of PipelineHandler."""

import asyncio

import pytest
from dingtalk_stream import AckMessage, ChatbotMessage
from unittest.mock import AsyncMock, MagicMock

from lib.handlers import BaseMessageHandler, PipelineHandler


def make_callback() -> "ChatbotMessage":
    return MagicMock(data={"msgtype": "text", "text": {"content": "1+1"}})


class BlockingHandler(BaseMessageHandler):
    """Simulates a download-in-progress task: awaits until cancelled."""

    def __init__(self):
        self.started = asyncio.Event()
        self.finished = False

    async def handle(self, message, raw_data, pipeline) -> bool:
        self.started.set()
        await asyncio.sleep(3600)
        self.finished = True
        return True


class CommittingHandler(BaseMessageHandler):
    """Simulates a past-download-point task: marks, then finishes naturally."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.finished = False

    async def handle(self, message, raw_data, pipeline) -> bool:
        pipeline.mark_download_done()
        await asyncio.sleep(self.delay)
        self.finished = True
        return True


class MarkingHandler(BaseMessageHandler):
    """Records whether mark_download_done found the calling task registered."""

    def __init__(self):
        self.was_registered = None

    async def handle(self, message, raw_data, pipeline) -> bool:
        task = asyncio.current_task()
        self.was_registered = task in pipeline._active_tasks
        return True


@pytest.mark.asyncio
async def test_gate_rejects_processing_after_begin_drain():
    handler = MagicMock(spec=BaseMessageHandler)
    handler.handle = AsyncMock(return_value=True)
    pipeline = PipelineHandler([handler])

    pipeline.begin_drain()
    status, msg = await pipeline.process(make_callback())

    assert (status, msg) == (AckMessage.STATUS_OK, "OK")
    handler.handle.assert_not_awaited()
    assert pipeline._active_tasks == {}


@pytest.mark.asyncio
async def test_task_registers_for_drain_and_deregisters_on_finish():
    handler = MarkingHandler()
    pipeline = PipelineHandler([handler])

    await pipeline.process(make_callback())

    assert handler.was_registered is True
    assert pipeline._active_tasks == {}


@pytest.mark.asyncio
async def test_drain_cancels_unmarked_task_which_replies_and_reraises():
    blocking = BlockingHandler()
    pipeline = PipelineHandler([blocking])
    pipeline.async_reply_text = AsyncMock()

    task = asyncio.create_task(pipeline.process(make_callback()))
    await asyncio.wait_for(blocking.started.wait(), timeout=1.0)
    assert task in pipeline._active_tasks

    pipeline.begin_drain()
    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=5.0), timeout=5.0)

    # The blocked task was cancelled: it must not have completed normally.
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)
    assert blocking.finished is False
    assert task.cancelled()
    assert pipeline._active_tasks == {}


@pytest.mark.asyncio
async def test_drain_waits_for_marked_task_to_finish_commit():
    committing = CommittingHandler()
    pipeline = PipelineHandler([committing])

    task = asyncio.create_task(pipeline.process(make_callback()))
    # Let the task reach mark_download_done() (set synchronously in handle).
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    pipeline.begin_drain()
    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=5.0), timeout=5.0)

    await asyncio.wait_for(task, timeout=1.0)
    assert committing.finished is True  # commit phase ran to completion
    assert not task.cancelled()
    assert pipeline._active_tasks == {}


@pytest.mark.asyncio
async def test_drain_on_empty_registry_returns_instantly():
    pipeline = PipelineHandler()
    pipeline.begin_drain()

    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=10.0), timeout=0.5)


@pytest.mark.asyncio
async def test_download_cancel_midstream_cleans_temp_file(tmp_path):
    """Cancelling a download mid-stream must remove the partial .tmp file."""
    import httpx

    from lib.file_downloader import FileDownloader

    async def slow_stream(_request):
        async def body():
            yield b"chunk-one"
            await asyncio.sleep(3600)

        return httpx.Response(200, content=body())

    downloader = FileDownloader(
        output_dir=str(tmp_path),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(slow_stream)),
    )

    task = asyncio.create_task(downloader.download_file_stream("https://example.com/file"))
    await asyncio.sleep(0.2)  # let the first chunk be written to the temp file
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    leftovers = list((tmp_path / ".tmp").glob("*.tmp"))
    assert leftovers == []


@pytest.mark.asyncio
async def test_drain_timeout_abandons_stuck_task(caplog):
    """A task that lingers after the first cancel (e.g. finishing an
    unbreakable cleanup) stays pending past the drain timeout and is
    abandoned with an INFO log."""

    class StubbornHandler(BaseMessageHandler):
        async def handle(self, message, raw_data, pipeline) -> bool:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass  # swallow the first cancel, linger a while
            await asyncio.sleep(0.3)
            raise asyncio.CancelledError

    pipeline = PipelineHandler([StubbornHandler()])

    task = asyncio.create_task(pipeline.process(make_callback()))
    await asyncio.sleep(0.05)  # let the task park in its first sleep

    pipeline.begin_drain()
    with caplog.at_level("INFO"):
        await asyncio.wait_for(pipeline.drain_active_tasks(timeout=0.05), timeout=1.0)

    assert "abandoning 1 unfinished task" in caplog.text
    with pytest.raises(asyncio.CancelledError):
        await task
