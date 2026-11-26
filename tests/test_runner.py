"""Unit tests for BotService and graceful shutdown signal handling."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from dingtalk_stream import CallbackMessage
from app.core.runner import BotService
from app.handlers import (
    BaseMessageHandler,
    PipelineHandler,
    ReplyIntent,
    ReplyTier,
)


@pytest.mark.asyncio
async def test_service_lifecycle_and_graceful_shutdown():
    client = MagicMock()
    cancelled = asyncio.Event()

    # Mock client.start to hang until cancelled.
    async def mock_start():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    client.start = mock_start
    client.stop = AsyncMock()
    client.websocket = AsyncMock()

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)
    notifier.send_offline_notification = AsyncMock(return_value=True)

    logger = MagicMock()
    service = BotService(client=client, notifier=notifier, logger=logger)

    # Run service.start_and_wait in a background task
    run_task = asyncio.create_task(service.start_and_wait())

    # Allow startup tasks to run
    await asyncio.sleep(0.01)
    notifier.send_online_notification.assert_awaited_once()

    # Trigger stop
    service.request_stop("SIGTERM")

    # Wait for start_and_wait to complete
    await asyncio.wait_for(run_task, timeout=2.0)

    # Spec: shutdown cancels the runner task; the SDK client is never
    # stopped directly (SDK 0.24.3 has no stop() API).
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_service_registers_sigint_and_sigterm_handlers():
    client = MagicMock()
    client.start = AsyncMock()
    client.websocket = None
    service = BotService(client=client, logger=MagicMock())

    loop = asyncio.get_running_loop()
    with patch.object(loop, "add_signal_handler") as mock_add_signal:
        await service.start()
        registered_sigs = [call.args[0] for call in mock_add_signal.call_args_list]
        assert signal.SIGINT in registered_sigs
        assert signal.SIGTERM in registered_sigs

        service.request_stop("SIGINT")
        await service.stop()


@pytest.mark.asyncio
async def test_service_without_notifier():
    client = MagicMock()
    started = asyncio.Event()

    async def mock_start():
        started.set()
        await asyncio.Event().wait()

    client.start = mock_start
    client.stop = AsyncMock()
    client.websocket = None
    logger = MagicMock()

    service = BotService(client=client, notifier=None, logger=logger)

    run_task = asyncio.create_task(service.start_and_wait())
    await asyncio.wait_for(started.wait(), timeout=1.0)

    service.request_stop("SIGINT")
    await asyncio.wait_for(run_task, timeout=2.0)


def test_run_forever_handles_exit():
    """Spec: second Ctrl-C (KeyboardInterrupt from start_and_wait) is
    re-raised so the process exits with non-zero status."""
    client = MagicMock()
    service = BotService(client=client)

    with patch.object(service, "start_and_wait", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            service.run_forever()


@pytest.mark.asyncio
async def test_shutdown_cancels_sdk_task_without_client_stop():
    """Spec: shutdown cancels the runner task within a bounded wait; the
    SDK client is never stopped directly (SDK 0.24.3 has no stop() API
    and no _stop_event attribute)."""
    client = MagicMock()
    cancelled = asyncio.Event()

    async def mock_start():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    client.start = mock_start
    client.stop = AsyncMock()
    client.websocket = None

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)
    notifier.send_offline_notification = AsyncMock(return_value=True)

    service = BotService(client=client, notifier=notifier, logger=MagicMock())

    run_task = asyncio.create_task(service.start_and_wait())
    await asyncio.sleep(0.01)

    service.request_stop("SIGINT")
    await asyncio.wait_for(run_task, timeout=2.0)

    assert cancelled.is_set()


def test_request_stop_raises_on_second_signal():
    """Spec: second request_stop() raises KeyboardInterrupt as force-exit escape hatch."""
    client = MagicMock()
    service = BotService(client=client, logger=MagicMock())

    # First request starts the graceful shutdown and returns normally.
    service.request_stop("SIGINT")

    with pytest.raises(KeyboardInterrupt):
        service.request_stop("SIGINT")


@pytest.mark.asyncio
async def test_shutdown_completes_when_offline_notify_throws():
    """Spec: offline notification failure (fire-and-forget) does not block shutdown.

    The notification is dispatched via asyncio.create_task and never awaited,
    so an exception in the notification task must not propagate to the service
    or change its exit code.
    """
    client = MagicMock()

    async def mock_start():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    async def mock_stop():
        pass

    client.start = mock_start
    client.stop = mock_stop
    client.websocket = None

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)
    notifier.send_offline_notification = AsyncMock(
        side_effect=RuntimeError("network down")
    )

    service = BotService(client=client, notifier=notifier, logger=MagicMock())

    run_task = asyncio.create_task(service.start_and_wait())
    await asyncio.sleep(0.01)

    service.request_stop("SIGINT")

    # Should complete without raising the RuntimeError
    await asyncio.wait_for(run_task, timeout=2.0)
    notifier.send_offline_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_is_idempotent():
    """Spec: BotService.start() called again after a successful start returns
    immediately without re-initialising."""
    client = MagicMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.websocket = None

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)
    notifier.send_offline_notification = AsyncMock(return_value=True)

    service = BotService(client=client, notifier=notifier, logger=MagicMock())

    await service.start()
    await service.start()
    await asyncio.sleep(0)

    # The SDK runner is launched exactly once and the online notification is
    # sent exactly once; a second start() is a no-op.
    client.start.assert_awaited_once()
    notifier.send_online_notification.assert_awaited_once()

    # Cleanup
    service.request_stop("SIGINT")
    await service.stop()


@pytest.mark.asyncio
async def test_start_passes_startup_staff_snapshot_to_online_notification():
    client = MagicMock()
    client.start = AsyncMock()
    client.websocket = None

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)

    service = BotService(
        client=client,
        notifier=notifier,
        logger=MagicMock(),
        startup_staff_snapshot="snapshot text",
    )

    await service.start()

    notifier.send_online_notification.assert_awaited_once_with("snapshot text")


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    """Spec: BotService.stop() called again after a successful stop returns
    immediately without re-running the shutdown sequence."""
    client = MagicMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.websocket = None

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)
    notifier.send_offline_notification = AsyncMock(return_value=True)

    service = BotService(client=client, notifier=notifier, logger=MagicMock())

    await service.start()
    service.request_stop("SIGINT")
    await service.stop()

    # Second call must be a no-op.
    await service.stop()


@pytest.mark.asyncio
async def test_scheduler_started_on_start_and_stopped_on_stop():
    client = MagicMock()
    client.start = AsyncMock()
    client.websocket = None

    scheduler = MagicMock()
    service = BotService(client=client, logger=MagicMock(), scheduler=scheduler)

    await service.start()
    scheduler.start.assert_called_once()

    service.request_stop("SIGINT")
    await service.stop()
    scheduler.stop.assert_called_once()


@pytest.mark.asyncio
async def test_startup_hook_runs_before_sdk_start():
    order = []

    async def hook():
        order.append("hook")

    async def mock_start():
        order.append("sdk")
        await asyncio.Event().wait()

    client = MagicMock()
    client.start = mock_start
    client.websocket = None

    service = BotService(client=client, logger=MagicMock(), startup_hook=hook)
    run_task = asyncio.create_task(service.start_and_wait())
    await asyncio.sleep(0.01)

    service.request_stop("SIGINT")
    await asyncio.wait_for(run_task, timeout=2.0)

    assert order[:2] == ["hook", "sdk"]


@pytest.mark.asyncio
async def test_startup_hook_failure_does_not_block_start():
    async def hook():
        raise RuntimeError("probe exploded")

    started = asyncio.Event()

    async def mock_start():
        started.set()
        await asyncio.Event().wait()

    client = MagicMock()
    client.start = mock_start
    client.websocket = None
    logger = MagicMock()

    service = BotService(client=client, logger=logger, startup_hook=hook)
    run_task = asyncio.create_task(service.start_and_wait())
    await asyncio.wait_for(started.wait(), timeout=1.0)

    service.request_stop("SIGINT")
    await asyncio.wait_for(run_task, timeout=2.0)


class _RecordingPipeline:
    """Minimal pipeline double that records the shutdown hooks' order."""

    def __init__(self, events):
        self._events = events

    def begin_drain(self):
        self._events.append("gate")

    async def drain_active_tasks(self, timeout=10.0):
        self._events.append("drain")


@pytest.mark.asyncio
async def test_stop_closes_connection_before_draining_pipeline():
    """Spec: intake is closed before in-flight work is drained."""
    events = []

    async def mock_start():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("runner_cancelled")
            raise

    async def close_websocket():
        events.append("ws_close")

    client = MagicMock()
    client.start = mock_start
    client.websocket = MagicMock()
    client.websocket.close = close_websocket

    service = BotService(
        client=client,
        logger=MagicMock(),
        pipeline=_RecordingPipeline(events),
    )
    await service.start()
    await asyncio.sleep(0)  # let the runner task enter its wait
    service.request_stop("SIGINT")
    await service.stop()

    assert events == ["runner_cancelled", "ws_close", "gate", "drain"]


@pytest.mark.asyncio
async def test_in_flight_message_replies_after_connection_closed():
    """Spec: a reply is delivered over sessionWebhook, not the websocket."""

    class SlowHandler(BaseMessageHandler):
        def __init__(self):
            self.started = asyncio.Event()
            self.finished = False

        async def handle(self, message, raw_data, pipeline):
            self.started.set()
            await asyncio.sleep(0.05)
            self.finished = True
            return ReplyIntent(tier=ReplyTier.PRIMARY, text="done")

    handler = SlowHandler()
    pipeline = PipelineHandler([handler])
    replies = []
    pipeline.reply_text = lambda text, _message: replies.append(text) or {"errcode": 0}

    client = MagicMock()
    client.start = AsyncMock()
    client.websocket = None  # connection already closed

    service = BotService(client=client, logger=MagicMock(), pipeline=pipeline)
    callback = CallbackMessage()
    callback.data = {"msgtype": "text", "text": {"content": "hi"}}
    await pipeline.process(callback)
    await asyncio.wait_for(handler.started.wait(), timeout=1.0)

    await service.stop()

    assert handler.finished is True
    assert replies == ["done"]
