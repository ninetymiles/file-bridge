"""Unit tests for PipelineHandler and BaseMessageHandler."""

import logging

import pytest
from unittest.mock import MagicMock, AsyncMock
from dingtalk_stream import CallbackMessage, AckMessage, ChatbotMessage
from app.handlers import BaseMessageHandler, PipelineHandler


class MockHandler(BaseMessageHandler):
    def __init__(self, should_handle: bool):
        self.should_handle = should_handle
        self.called = False

    async def handle(self, message: ChatbotMessage, raw_data: dict, pipeline: PipelineHandler) -> bool:
        self.called = True
        return self.should_handle


@pytest.mark.asyncio
async def test_pipeline_execution_order():
    h1 = MockHandler(should_handle=False)
    h2 = MockHandler(should_handle=True)
    h3 = MockHandler(should_handle=False)

    pipeline = PipelineHandler([h1, h2, h3])

    callback = CallbackMessage()
    callback.data = {
        "msgtype": "text",
        "text": {"content": "test"},
    }

    status, msg = await pipeline.process(callback)
    assert status == AckMessage.STATUS_OK
    assert msg == "OK"
    assert h1.called is True
    assert h2.called is True
    assert h3.called is False  # halted after h2 handled it


@pytest.mark.asyncio
async def test_async_reply_text(monkeypatch):
    pipeline = PipelineHandler()
    mock_reply = MagicMock(return_value={"errcode": 0})
    monkeypatch.setattr(pipeline, "reply_text", mock_reply)

    incoming_msg = ChatbotMessage()
    incoming_msg.session_webhook = "https://mock.webhook"

    result = await pipeline.async_reply_text("hello", incoming_msg)
    assert result == {"errcode": 0}
    mock_reply.assert_called_once_with("hello", incoming_msg)


@pytest.mark.asyncio
async def test_debug_logs_headers_and_full_raw_data(caplog):
    pipeline = PipelineHandler()
    callback = CallbackMessage()
    callback.headers.topic = "/v1.0/im/bot/messages/get"
    callback.headers.message_id = "msg123"
    callback.data = {
        "msgtype": "text",
        "text": {"content": "你好"},
        "msgId": "abc",
    }

    with caplog.at_level(logging.DEBUG):
        await pipeline.process(callback)

    assert "msg123" in caplog.text
    assert "/v1.0/im/bot/messages/get" in caplog.text
    # Chinese must be emitted verbatim, not unicode-escaped, and payload untruncated.
    assert "你好" in caplog.text
    header_logs = [r for r in caplog.records if r.getMessage().startswith("Callback headers:")]
    raw_logs = [r for r in caplog.records if r.getMessage().startswith("Message raw data:")]
    assert len(header_logs) == 1
    assert len(raw_logs) == 1


@pytest.mark.asyncio
async def test_debug_diagnostic_logs_hidden_at_info_level(caplog):
    pipeline = PipelineHandler()
    callback = CallbackMessage()
    callback.headers.message_id = "msg456"
    callback.data = {"msgtype": "text", "text": {"content": "hello"}}

    with caplog.at_level(logging.INFO):
        await pipeline.process(callback)

    diagnostic_logs = [
        r for r in caplog.records
        if r.getMessage().startswith(("Callback headers:", "Message raw data:"))
    ]
    assert diagnostic_logs == []
    # The INFO summary remains visible.
    assert any("Received message from" in r.getMessage() for r in caplog.records)
