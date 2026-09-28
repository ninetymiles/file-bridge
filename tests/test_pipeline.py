"""Unit tests for PipelineHandler and BaseMessageHandler."""

import pytest
from unittest.mock import MagicMock
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
