"""Unit tests for LifecycleNotifier."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest
from lib.lifecycle_notifier import LifecycleNotifier


@pytest.mark.asyncio
async def test_unconfigured_notification_silently_skips():
    logger = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=None,
        notify_conversation_id=None,
        notify_user_id=None,
        logger=logger,
    )
    assert not notifier.is_configured
    result = await notifier.send_online_notification()
    assert result is True
    logger.debug.assert_called()


@pytest.mark.asyncio
async def test_group_notification_success():
    client = MagicMock()
    logger = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
        logger=logger,
    )
    assert notifier.is_configured

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        result = await notifier.send_online_notification()

        assert result is True
        mock_handler_inst.reply_markdown_card.assert_called_once()
        args, kwargs = mock_handler_inst.reply_markdown_card.call_args
        assert "上线" in args[0]
        assert kwargs.get("title") == "🤖 File Bridge 机器人已上线"


@pytest.mark.asyncio
async def test_single_user_notification_success():
    client = MagicMock()
    logger = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_user_id="user_staff_456",
        logger=logger,
    )
    assert notifier.is_configured

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        result = await notifier.send_offline_notification()

        assert result is True
        mock_handler_inst.reply_markdown_card.assert_called_once()
        args, kwargs = mock_handler_inst.reply_markdown_card.call_args
        assert "离线" in args[0]
        assert kwargs.get("title") == "🛑 File Bridge 机器人已离线"


@pytest.mark.asyncio
async def test_notification_exception_does_not_crash():
    client = MagicMock()
    logger = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
        logger=logger,
    )

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        mock_handler_inst.reply_markdown_card.side_effect = RuntimeError("Network error")

        result = await notifier.send_online_notification()
        assert result is False
        logger.warning.assert_called()


@pytest.mark.asyncio
async def test_notification_timeout_handled():
    client = MagicMock()
    logger = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
        logger=logger,
        timeout=0.01,
    )

    def slow_send(*args, **kwargs):
        import time
        time.sleep(0.05)

    with patch.object(notifier, "_send_sync", side_effect=slow_send):
        result = await notifier.send_online_notification()
        assert result is False
        logger.warning.assert_called()
