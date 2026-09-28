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
    assert handled is False
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

    # Platform strips @ prefix, leaving leading whitespace
    raw_data = {
        "msgtype": "text",
        "text": {"content": " 重建索引 "},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is False
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


def test_merge_rich_text_strips_at_prefix():
    segments = [
        {"text": "@FileBridge"},
        {"text": "重建索引"},
        {"text": "\n"},
        {"type": "picture", "downloadCode": "code1"},
    ]
    assert CommandHandler._merge_rich_text(segments) == "重建索引\n<img1>"


def test_merge_rich_text_strips_at_suffix():
    segments = [
        {"type": "picture", "downloadCode": "code1"},
        {"text": "\n"},
        {"text": "@FileBridge"},
    ]
    assert CommandHandler._merge_rich_text(segments) == "<img1>\n"


def test_merge_rich_text_private_chat_no_at():
    segments = [
        {"type": "picture", "downloadCode": "code1"},
        {"text": "\n"},
        {"type": "picture", "downloadCode": "code2"},
    ]
    assert CommandHandler._merge_rich_text(segments) == "<img1>\n<img2>"


def test_merge_rich_text_text_only():
    segments = [
        {"text": "hello"},
        {"text": " "},
        {"text": "world"},
    ]
    assert CommandHandler._merge_rich_text(segments) == "hello world"


@pytest.mark.asyncio
async def test_command_handler_rich_text_triggers_command():
    mock_store = MagicMock()
    mock_store.async_rebuild_index = AsyncMock(return_value=(3, 10))

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = CommandHandler(metadata_store=mock_store)

    raw_data = {
        "msgtype": "richText",
        "content": {
            "richText": [
                {"text": "@FileBridge"},
                {"text": "重建索引"},
                {"type": "picture", "downloadCode": "code1"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is False
    mock_store.async_rebuild_index.assert_called_once()
    mock_pipeline.async_reply_text.assert_called_once_with(
        "索引重建完成，清理元数据 3 条，现有有效索引 10 条。",
        msg,
    )


@pytest.mark.asyncio
async def test_command_handler_rich_text_no_command():
    mock_store = MagicMock()
    mock_store.async_rebuild_index = AsyncMock()

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = CommandHandler(metadata_store=mock_store)

    raw_data = {
        "msgtype": "richText",
        "content": {
            "richText": [
                {"text": "@FileBridge"},
                {"text": "abcd"},
                {"type": "picture", "downloadCode": "code1"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is False
    mock_store.async_rebuild_index.assert_not_called()
    mock_pipeline.async_reply_text.assert_not_called()
