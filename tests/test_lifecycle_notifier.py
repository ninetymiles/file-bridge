"""Unit tests for LifecycleNotifier."""

from unittest.mock import MagicMock, patch
import pytest
from app.services.lifecycle_notifier import LifecycleNotifier


@pytest.mark.asyncio
async def test_unconfigured_notification_silently_skips():
    notifier = LifecycleNotifier(
        dingtalk_client=None,
        notify_conversation_id=None,
        notify_staff_id=None,
    )
    assert not notifier.is_configured
    result = await notifier.send_online_notification()
    assert result is True


@pytest.mark.asyncio
async def test_group_notification_success():
    client = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
    )
    assert notifier.is_configured

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        mock_handler_inst.reply_markdown_card.return_value = MagicMock(card_instance_id="card-1")
        result = await notifier.send_online_notification()

        assert result is True
        mock_handler_inst.reply_markdown_card.assert_called_once()
        args, kwargs = mock_handler_inst.reply_markdown_card.call_args
        assert "上线" in args[0]
        assert kwargs.get("title") == "🤖 File Bridge 机器人已上线"


@pytest.mark.asyncio
async def test_single_staff_notification_success():
    client = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_staff_id="staff_456",
    )
    assert notifier.is_configured

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        mock_handler_inst.reply_markdown_card.return_value = MagicMock(card_instance_id="card-1")
        result = await notifier.send_offline_notification()

        assert result is True
        mock_handler_inst.reply_markdown_card.assert_called_once()
        args, kwargs = mock_handler_inst.reply_markdown_card.call_args
        assert "离线" in args[0]
        assert kwargs.get("title") == "🛑 File Bridge 机器人已离线"


@pytest.mark.asyncio
async def test_both_targets_each_receive_notification():
    client = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
        notify_staff_id="staff_456",
    )

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler, \
            patch("dingtalk_stream.reply_specified_group_chat") as mock_group, \
            patch("dingtalk_stream.reply_specified_single_chat") as mock_staff:
        group_message = MagicMock(name="group_message")
        staff_message = MagicMock(name="staff_message")
        mock_group.return_value = group_message
        mock_staff.return_value = staff_message

        mock_handler_inst = MockHandler.return_value
        mock_handler_inst.reply_markdown_card.return_value = MagicMock(card_instance_id="card-1")

        result = await notifier.send_online_notification()

        assert result is True
        mock_group.assert_called_once_with("cid_group_123")
        mock_staff.assert_called_once_with("staff_456")
        assert mock_handler_inst.reply_markdown_card.call_count == 2
        # Fixed sending order: group first, staff second.
        assert mock_handler_inst.reply_markdown_card.call_args_list[0].args[1] is group_message
        assert mock_handler_inst.reply_markdown_card.call_args_list[1].args[1] is staff_message


@pytest.mark.asyncio
async def test_one_target_exception_does_not_block_other():
    client = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
        notify_staff_id="staff_456",
    )

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        mock_handler_inst.reply_markdown_card.side_effect = [
            RuntimeError("Network error"),
            MagicMock(card_instance_id="card-ok"),
        ]

        result = await notifier.send_online_notification()

        assert result is False
        assert mock_handler_inst.reply_markdown_card.call_count == 2


@pytest.mark.asyncio
async def test_empty_card_instance_id_counts_as_failure():
    client = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
    )

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        mock_handler_inst.reply_markdown_card.return_value = MagicMock(card_instance_id="")

        result = await notifier.send_online_notification()

        assert result is False
        mock_handler_inst.reply_markdown_card.assert_called_once()


@pytest.mark.asyncio
async def test_notification_exception_does_not_crash():
    client = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
    )

    with patch("dingtalk_stream.ChatbotHandler") as MockHandler:
        mock_handler_inst = MockHandler.return_value
        mock_handler_inst.reply_markdown_card.side_effect = RuntimeError("Network error")

        result = await notifier.send_online_notification()
        assert result is False


@pytest.mark.asyncio
async def test_notification_timeout_handled():
    client = MagicMock()
    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id="cid_group_123",
        timeout=0.01,
    )

    def slow_send(*_args, **_kwargs):
        import time
        time.sleep(0.05)

    with patch.object(notifier, "_send_sync", side_effect=slow_send):
        result = await notifier.send_online_notification()
        assert result is False
