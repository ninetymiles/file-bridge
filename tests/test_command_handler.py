"""Unit tests for CommandHandler dispatch behavior."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dingtalk_stream import ChatbotMessage
from app.handlers import CommandHandler, PipelineHandler
from app.handlers.message import (
    CAPABILITY_VARIANTS,
    GUIDE_BODY_TEMPLATES,
    GUIDE_ENDING_TEXTS,
    UNMATCHED_PREFIX_TEXTS,
    build_guide_reply,
)


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
    pipeline.async_reply_text = AsyncMock()
    return handler, matcher, action, pipeline


def _guide_reply(mock_pipeline) -> str:
    return mock_pipeline.async_reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_command_handler_dispatches_matched_command():
    handler, matcher, action, pipeline = _handler("rebuild_index")
    raw_data = {"msgtype": "text", "text": {"content": "重建索引"}}
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["重建索引"]
    action.assert_awaited_once_with(msg, raw_data, pipeline)
    pipeline.async_reply_text.assert_not_awaited()


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
async def test_command_handler_replies_unmatched_text_with_guide():
    handler, matcher, action, pipeline = _handler(None)
    raw_data = {"msgtype": "text", "text": {"content": "hello world"}}
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["hello world"]
    action.assert_not_awaited()
    pipeline.async_reply_text.assert_awaited_once()

    reply = _guide_reply(pipeline)
    assert any(reply.startswith(prefix) for prefix in UNMATCHED_PREFIX_TEXTS)
    assert reply.endswith(tuple(GUIDE_ENDING_TEXTS))


@pytest.mark.asyncio
async def test_command_handler_ignores_non_text():
    handler, matcher, action, pipeline = _handler("rebuild_index")
    raw_data = {"msgtype": "picture", "content": {"downloadCode": "abc"}}
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == []
    action.assert_not_awaited()
    pipeline.async_reply_text.assert_not_awaited()


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
    pipeline.async_reply_text.assert_not_awaited()


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
    pipeline.async_reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_handler_rich_text_suppresses_guide_with_picture():
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
    pipeline.async_reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_handler_empty_mention_gets_guide_without_prefix():
    handler, matcher, action, pipeline = _handler(None)
    raw_data = {
        "msgtype": "richText",
        "content": {"richText": [{"text": "@FileBridge"}]},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == []
    action.assert_not_awaited()
    pipeline.async_reply_text.assert_awaited_once()

    reply = _guide_reply(pipeline)
    assert not any(prefix in reply for prefix in UNMATCHED_PREFIX_TEXTS)
    assert reply.endswith(tuple(GUIDE_ENDING_TEXTS))
    assert reply.count("• ") == len(CAPABILITY_VARIANTS)


@pytest.mark.asyncio
async def test_command_handler_text_only_richtext_gets_guide():
    handler, matcher, action, pipeline = _handler(None)
    raw_data = {
        "msgtype": "richText",
        "content": {
            "richText": [
                {"text": "@FileBridge"},
                {"text": "abcd"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, pipeline)

    assert handled is False
    assert matcher.received_texts == ["abcd"]
    action.assert_not_awaited()
    pipeline.async_reply_text.assert_awaited_once()

    reply = _guide_reply(pipeline)
    assert any(reply.startswith(prefix) for prefix in UNMATCHED_PREFIX_TEXTS)


def test_build_guide_reply_with_text_keeps_dimension_order(monkeypatch):
    # Deterministic pick: every random.choice returns the first candidate,
    # so the exact assembled string can be asserted (prefix-body-ending).
    monkeypatch.setattr("app.handlers.message.random.choice", lambda seq: seq[0])

    lines = [f"• {variants[0]}" for variants in CAPABILITY_VARIANTS]
    lines[-1] = f"{lines[-1]}。"
    expected = (
        f"{UNMATCHED_PREFIX_TEXTS[0]}{GUIDE_BODY_TEMPLATES[0].format(caps=chr(10).join(lines))}"
        f"\n{GUIDE_ENDING_TEXTS[0]}"
    )

    assert build_guide_reply(has_real_text=True) == expected


def test_build_guide_reply_empty_text_has_no_prefix(monkeypatch):
    monkeypatch.setattr("app.handlers.message.random.choice", lambda seq: seq[0])

    reply = build_guide_reply(has_real_text=False)

    assert not reply.startswith(tuple(UNMATCHED_PREFIX_TEXTS))
    assert reply.startswith(GUIDE_BODY_TEMPLATES[0].split("\n", 1)[0])
    assert reply.endswith(GUIDE_ENDING_TEXTS[0])


def test_merge_rich_text_strips_at_prefix():
    segments = [
        {"text": "@FileBridge"},
        {"text": "重建索引"},
        {"text": "\n"},
        {"type": "picture", "downloadCode": "code1"},
    ]
    merged, has_picture = CommandHandler._merge_rich_text(segments)
    assert merged == "重建索引\n<img1>"
    assert has_picture is True


def test_merge_rich_text_strips_at_suffix():
    segments = [
        {"type": "picture", "downloadCode": "code1"},
        {"text": "\n"},
        {"text": "@FileBridge"},
    ]
    merged, has_picture = CommandHandler._merge_rich_text(segments)
    assert merged == "<img1>\n"
    assert has_picture is True


def test_merge_rich_text_private_chat_no_at():
    segments = [
        {"type": "picture", "downloadCode": "code1"},
        {"text": "\n"},
        {"type": "picture", "downloadCode": "code2"},
    ]
    merged, has_picture = CommandHandler._merge_rich_text(segments)
    assert merged == "<img1>\n<img2>"
    assert has_picture is True


def test_merge_rich_text_text_only():
    segments = [
        {"text": "hello"},
        {"text": " "},
        {"text": "world"},
    ]
    merged, has_picture = CommandHandler._merge_rich_text(segments)
    assert merged == "hello world"
    assert has_picture is False
