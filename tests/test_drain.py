"""Unit tests for the shutdown drain mechanics of PipelineHandler."""

import asyncio

import pytest
from dingtalk_stream import AckMessage, ChatbotMessage
from unittest.mock import AsyncMock, MagicMock

from app.handlers import BaseMessageHandler, PipelineHandler, ReplyIntent, ReplyTier


def make_callback() -> "ChatbotMessage":
    return MagicMock(data={"msgtype": "text", "text": {"content": "1+1"}})


class DownloadingHandler(BaseMessageHandler):
    """Mirrors MediaFileHandler: owns an interruptible download sub-task.

    cancel_tasks() cancels the in-flight download; handle() catches the
    cancellation, replies, and returns True so the SDK task ends normally.
    """

    def __init__(self):
        self.download_started = asyncio.Event()
        self.replied_cancellation = False
        self._interruptible_tasks: set[asyncio.Task] = set()

    def cancel_tasks(self) -> None:
        for task in list(self._interruptible_tasks):
            task.cancel()

    async def handle(self, message, raw_data, pipeline):
        async def download():
            self.download_started.set()
            await asyncio.sleep(3600)

        download_task = asyncio.create_task(download())
        self._interruptible_tasks.add(download_task)
        try:
            await download_task
        except asyncio.CancelledError:
            self.replied_cancellation = True
            return ReplyIntent(tier=ReplyTier.PRIMARY, text="服务正在关闭，下载任务已取消")
        finally:
            self._interruptible_tasks.discard(download_task)
        return None


class ArchivingHandler(BaseMessageHandler):
    """Download completes fast, then archive runs inline (non-interruptible).

    cancel_tasks() finds nothing to cancel once download is done; archive
    must always finish even when drain begins mid-archive.
    """

    def __init__(self, archive_delay: float = 0.05):
        self.archive_finished = False
        self.archive_delay = archive_delay
        self._interruptible_tasks: set[asyncio.Task] = set()

    def cancel_tasks(self) -> None:
        for task in list(self._interruptible_tasks):
            task.cancel()

    async def handle(self, message, raw_data, pipeline):
        async def download():
            return "done"

        download_task = asyncio.create_task(download())
        self._interruptible_tasks.add(download_task)
        try:
            await download_task
        finally:
            self._interruptible_tasks.discard(download_task)

        # Archive: non-interruptible, must finish regardless of drain.
        await asyncio.sleep(self.archive_delay)
        self.archive_finished = True
        return None


class MarkingHandler(BaseMessageHandler):
    """Records whether the SDK task was registered during handle()."""

    def __init__(self):
        self.was_registered = None

    async def handle(self, message, raw_data, pipeline):
        task = asyncio.current_task()
        self.was_registered = task in pipeline._active_tasks
        return None


@pytest.mark.asyncio
async def test_gate_rejects_processing_after_begin_drain():
    handler = MagicMock(spec=BaseMessageHandler)
    handler.handle = AsyncMock(return_value=True)
    pipeline = PipelineHandler([handler])

    pipeline.begin_drain()
    status, msg = await pipeline.process(make_callback())

    assert (status, msg) == (AckMessage.STATUS_OK, "OK")
    handler.handle.assert_not_awaited()
    assert pipeline._active_tasks == set()


@pytest.mark.asyncio
async def test_task_registers_for_drain_and_deregisters_on_finish():
    handler = MarkingHandler()
    pipeline = PipelineHandler([handler])

    await pipeline.process(make_callback())

    assert handler.was_registered is True
    assert pipeline._active_tasks == set()


@pytest.mark.asyncio
async def test_begin_drain_cancels_interruptible_download_via_handler():
    downloading = DownloadingHandler()
    pipeline = PipelineHandler([downloading])
    pipeline.async_reply_text = AsyncMock()

    task = asyncio.create_task(pipeline.process(make_callback()))
    await asyncio.wait_for(downloading.download_started.wait(), timeout=1.0)
    assert task in pipeline._active_tasks

    pipeline.begin_drain()
    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=5.0), timeout=5.0)

    # SDK task ends normally: handler caught the sub-task cancellation,
    # replied, and returned True. It was NOT cancelled itself.
    await asyncio.wait_for(task, timeout=1.0)
    assert downloading.replied_cancellation is True
    assert not task.cancelled()
    assert pipeline._active_tasks == set()


@pytest.mark.asyncio
async def test_drain_waits_for_non_interruptible_archive_to_finish():
    archiving = ArchivingHandler()
    pipeline = PipelineHandler([archiving])

    task = asyncio.create_task(pipeline.process(make_callback()))
    # Let download finish and archive start.
    await asyncio.sleep(0.01)

    pipeline.begin_drain()
    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=5.0), timeout=5.0)

    await asyncio.wait_for(task, timeout=1.0)
    assert archiving.archive_finished is True  # archive ran to completion
    assert not task.cancelled()
    assert pipeline._active_tasks == set()


@pytest.mark.asyncio
async def test_drain_on_empty_registry_returns_instantly():
    pipeline = PipelineHandler()
    pipeline.begin_drain()

    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=10.0), timeout=0.5)


@pytest.mark.asyncio
async def test_download_cancel_midstream_cleans_temp_file(tmp_path):
    """Cancelling a download mid-stream must remove the partial .tmp file."""
    import httpx

    from app.services.file_downloader import FileDownloader

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
async def test_drain_timeout_abandons_stuck_task():
    """A handler stuck in non-interruptible work cannot be cancelled by drain.

    drain waits, times out, and abandons the task; the task remains pending
    after drain returns (it is cleaned up manually by the test).
    """

    class StuckHandler(BaseMessageHandler):
        async def handle(self, message, raw_data, pipeline):
            await asyncio.sleep(3600)
            return None

    pipeline = PipelineHandler([StuckHandler()])

    task = asyncio.create_task(pipeline.process(make_callback()))
    await asyncio.sleep(0.05)  # let the task park in its sleep

    pipeline.begin_drain()
    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=0.05), timeout=1.0)

    # Stuck task is still pending: drain could not cancel it.
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
