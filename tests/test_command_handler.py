"""Unit tests for CommandHandler dispatch behavior."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dingtalk_stream import ChatbotMessage
from app.handlers import CommandHandler, PipelineHandler


class FakeMatcher:
    """Matcher test double: returns a fixed command id and records inputs."""

    def __init__(self, command_id=None):
        self._command_id = command_id
        self.received_texts = []

    async def match(self, text):
        self.received_texts.append(text)
        return self._command_id


def _handler(command_id=None):
    matcher = FakeMatcher(command_id)
    action = AsyncMock()
    dispatch_table = {"rebuild_index": action}
    handler = CommandHandler(matcher=matcher, dispatch_table=dispatch_table)
    pipeline = MagicMock(spec=PipelineHandler)
    return handler, matcher, action, pipeline


@pytest.mark.asyncio
async def test_command_handler_dispatches_matched_command():
    handler, matcher, action, pipeline = _handler("rebuild_index")
    raw_data = {"msgtype": "text", "text": {"content": "重建索引"}}
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["重建索引"]
    action.assert_awaited_once_with(msg, raw_data, pipeline)


@pytest.mark.asyncio
async def test_command_handler_normalizes_text_before_matching():
    handler, matcher, action, pipeline = _handler("rebuild_index")
    raw_data = {"msgtype": "text", "text": {"content": " 重建索引 "}}
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["重建索引"]
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_command_handler_ignores_unmatched_text():
    handler, matcher, action, pipeline = _handler(None)
    raw_data = {"msgtype": "text", "text": {"content": "hello world"}}
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["hello world"]
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_handler_ignores_non_text():
    handler, matcher, action, pipeline = _handler("rebuild_index")
    raw_data = {"msgtype": "picture", "content": {"downloadCode": "abc"}}
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == []
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_handler_skips_matcher_for_placeholder_only_richtext():
    handler, matcher, action, pipeline = _handler("rebuild_index")
    raw_data = {
        "msgtype": "richText",
        "content": {"richText": [{"type": "picture", "downloadCode": "code1"}]},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == []
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_handler_rich_text_dispatches_command():
    handler, matcher, action, pipeline = _handler("rebuild_index")
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

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["重建索引"]
    action.assert_awaited_once_with(msg, raw_data, pipeline)


@pytest.mark.asyncio
async def test_command_handler_rich_text_no_command():
    handler, matcher, action, pipeline = _handler(None)
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

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["abcd"]
    action.assert_not_awaited()


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
