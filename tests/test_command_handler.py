"""Unit tests for CommandHandler."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dingtalk_stream import ChatbotMessage
from app.handlers import CommandHandler, PipelineHandler


@pytest.mark.asyncio
async def test_command_handler_matches_rebuild_index():
    mock_store = MagicMock()
    mock_store.async_rebuild_index = AsyncMock(return_value=(5, 12))

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = CommandHandler(metadata_store=mock_store)

    # Test exact match
    raw_data = {
        "msgtype": "text",
        "text": {"content": "重建索引"},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is True
    mock_store.async_rebuild_index.assert_called_once()
    mock_pipeline.async_reply_text.assert_called_once_with(
        "索引重建完成，清理元数据 5 条，现有有效索引 12 条。",
        msg,
    )


@pytest.mark.asyncio
async def test_command_handler_matches_at_bot_rebuild_index():
    mock_store = MagicMock()
    mock_store.async_rebuild_index = AsyncMock(return_value=(0, 20))

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = CommandHandler(metadata_store=mock_store)

    raw_data = {
        "msgtype": "text",
        "text": {"content": "@Bot 重建索引 "},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is True
    mock_store.async_rebuild_index.assert_called_once()
    mock_pipeline.async_reply_text.assert_called_once_with(
        "索引重建完成，清理元数据 0 条，现有有效索引 20 条。",
        msg,
    )


@pytest.mark.asyncio
async def test_command_handler_ignores_other_text():
    mock_store = MagicMock()
    mock_store.async_rebuild_index = AsyncMock()

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = CommandHandler(metadata_store=mock_store)

    raw_data = {
        "msgtype": "text",
        "text": {"content": "hello world"},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is False
    mock_store.async_rebuild_index.assert_not_called()
    mock_pipeline.async_reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_command_handler_ignores_non_text():
    mock_store = MagicMock()
    mock_store.async_rebuild_index = AsyncMock()

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = CommandHandler(metadata_store=mock_store)

    raw_data = {
        "msgtype": "picture",
        "content": {"downloadCode": "abc"},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is False
    mock_store.async_rebuild_index.assert_not_called()
    mock_pipeline.async_reply_text.assert_not_called()
