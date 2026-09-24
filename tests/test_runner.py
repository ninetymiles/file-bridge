"""Unit tests for BotService and graceful shutdown signal handling."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from lib.runner import BotService


@pytest.mark.asyncio
async def test_service_lifecycle_and_graceful_shutdown():
    client = MagicMock()
    # Mock client.start to hang until cancelled
    async def mock_start():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

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

    # Spec: shutdown sequence calls client.stop() before runner_task.cancel()
    client.stop.assert_awaited_once()
    assert service._runner_task.done()


@pytest.mark.asyncio
async def test_service_signal_handlers_registered():
    client = MagicMock()
    client.start = AsyncMock()
    logger = MagicMock()

    service = BotService(client=client, logger=logger)

    loop = asyncio.get_running_loop()
    with patch.object(loop, "add_signal_handler") as mock_add_signal:
        service._setup_signal_handlers(loop)
        registered_sigs = [call.args[0] for call in mock_add_signal.call_args_list]
        assert signal.SIGINT in registered_sigs
        assert signal.SIGTERM in registered_sigs


@pytest.mark.asyncio
async def test_service_without_notifier():
    client = MagicMock()
    async def mock_start():
        await asyncio.Event().wait()

    client.start = mock_start
    client.stop = AsyncMock()
    client.websocket = None
    logger = MagicMock()

    service = BotService(client=client, notifier=None, logger=logger)

    run_task = asyncio.create_task(service.start_and_wait())
    await asyncio.sleep(0.01)

    service.request_stop("SIGINT")
    await asyncio.wait_for(run_task, timeout=2.0)

    assert service._runner_task.done()


def test_run_forever_handles_exit():
    """Spec: second Ctrl-C (KeyboardInterrupt from start_and_wait) is
    re-raised so the process exits with non-zero status."""
    client = MagicMock()
    service = BotService(client=client)

    with patch.object(service, "start_and_wait", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            service.run_forever()


@pytest.mark.asyncio
async def test_shutdown_calls_client_stop_before_runner_task_cancel():
    """Spec: shutdown sequence is client.stop() -> runner_task.cancel().

    Setting SDK _stop_event first ensures the reconnect loop exits cleanly
    and is not treated as a network exception triggering reconnect.
    """
    call_order = []

    client = MagicMock()

    async def mock_stop():
        call_order.append("client.stop")

    async def mock_start():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            call_order.append("task.cancelled")
            raise

    client.start = mock_start
    client.stop = mock_stop
    client.websocket = None

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)
    notifier.send_offline_notification = AsyncMock(return_value=True)

    service = BotService(client=client, notifier=notifier, logger=MagicMock())

    run_task = asyncio.create_task(service.start_and_wait())
    await asyncio.sleep(0.01)

    service.request_stop("SIGINT")
    await asyncio.wait_for(run_task, timeout=2.0)

    assert "client.stop" in call_order
    assert "task.cancelled" in call_order
    assert call_order.index("client.stop") < call_order.index("task.cancelled")


def test_request_stop_raises_on_second_signal():
    """Spec: second request_stop() raises KeyboardInterrupt as force-exit escape hatch."""
    client = MagicMock()
    service = BotService(client=client, logger=MagicMock())

    service._is_shutting_down = True  # Simulate already shutting down

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
    assert service._runner_task.done()


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
    first_runner_task = service._runner_task

    # Second call must be a no-op
    await service.start()
    assert service._runner_task is first_runner_task
    # Online notification should have been sent exactly once
    notifier.send_online_notification.assert_awaited_once()

    # Cleanup
    service.request_stop("SIGINT")
    await service.stop()


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

    client.stop.assert_awaited_once()
    # Second call must not call client.stop() again
    await service.stop()
    client.stop.assert_awaited_once()
