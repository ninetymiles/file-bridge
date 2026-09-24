"""Unit tests for BotRunner and graceful shutdown signal handling."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from lib.runner import BotRunner


@pytest.mark.asyncio
async def test_runner_lifecycle_and_graceful_shutdown():
    client = MagicMock()
    # Mock client.start to hang until cancelled
    async def mock_start():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    client.start = mock_start
    client.websocket = AsyncMock()

    notifier = MagicMock()
    notifier.send_online_notification = AsyncMock(return_value=True)
    notifier.send_offline_notification = AsyncMock(return_value=True)

    logger = MagicMock()
    runner = BotRunner(client=client, notifier=notifier, logger=logger)

    # Run runner in a background task
    run_task = asyncio.create_task(runner.run())

    # Allow startup tasks to run
    await asyncio.sleep(0.01)
    notifier.send_online_notification.assert_awaited_once()

    # Trigger stop
    runner.request_stop("SIGTERM")

    # Wait for runner.run to complete
    await asyncio.wait_for(run_task, timeout=1.0)

    notifier.send_offline_notification.assert_awaited_once()
    client.websocket.close.assert_awaited_once()
    assert runner._runner_task.done()


@pytest.mark.asyncio
async def test_runner_signal_handlers_registered():
    client = MagicMock()
    client.start = AsyncMock()
    logger = MagicMock()

    runner = BotRunner(client=client, logger=logger)

    loop = asyncio.get_running_loop()
    with patch.object(loop, "add_signal_handler") as mock_add_signal:
        runner._setup_signal_handlers(loop)
        registered_sigs = [call.args[0] for call in mock_add_signal.call_args_list]
        assert signal.SIGINT in registered_sigs
        assert signal.SIGTERM in registered_sigs


@pytest.mark.asyncio
async def test_runner_without_notifier():
    client = MagicMock()
    async def mock_start():
        await asyncio.Event().wait()

    client.start = mock_start
    client.websocket = None
    logger = MagicMock()

    runner = BotRunner(client=client, notifier=None, logger=logger)

    run_task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.01)

    runner.request_stop("SIGINT")
    await asyncio.wait_for(run_task, timeout=1.0)

    assert runner._runner_task.done()


def test_start_forever_handles_exit():
    client = MagicMock()
    runner = BotRunner(client=client)

    with patch.object(runner, "run", side_effect=KeyboardInterrupt):
        # Should not raise exception
        runner.start_forever()
