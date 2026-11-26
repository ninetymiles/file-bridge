"""Unit tests for PipelineHandler and BaseMessageHandler."""

import asyncio

import pytest
from unittest.mock import MagicMock
from dingtalk_stream import CallbackMessage, AckMessage, ChatbotMessage
from app.handlers import (
    BaseMessageHandler,
    PipelineHandler,
    ReplyIntent,
    ReplyTier,
)
from conftest import process_and_wait


class MockHandler(BaseMessageHandler):
    def __init__(self, should_handle: bool):
        self.should_handle = should_handle
        self.called = False

    async def handle(self, message: ChatbotMessage, raw_data: dict, pipeline: PipelineHandler) -> ReplyIntent | None:
        self.called = True
        return None


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

    status, msg = await process_and_wait(pipeline, callback)
    assert status == AckMessage.STATUS_OK
    assert msg == "OK"
    assert h1.called is True
    assert h2.called is True
    assert h3.called is True  # no short-circuit in intent-reporting chain


@pytest.mark.asyncio
async def test_process_acknowledges_before_slow_handler_finishes():
    """Ack timing must not depend on handler duration (decoupled ack)."""
    release = asyncio.Event()
    handled = asyncio.Event()
    replies = []

    class SlowHandler(BaseMessageHandler):
        async def handle(self, message, raw_data, pipeline):
            handled.set()
            await release.wait()
            return ReplyIntent(tier=ReplyTier.PRIMARY, text="done")

    pipeline = PipelineHandler([SlowHandler()])
    pipeline.reply_text = lambda text, _message: replies.append(text) or {"errcode": 0}

    callback = CallbackMessage()
    callback.data = {"msgtype": "text", "text": {"content": "test"}}

    loop = asyncio.get_running_loop()
    started = loop.time()
    status, msg = await pipeline.process(callback)
    elapsed = loop.time() - started

    assert (status, msg) == (AckMessage.STATUS_OK, "OK")
    assert elapsed < 0.05
    assert replies == []

    await asyncio.wait_for(handled.wait(), timeout=1.0)
    release.set()
    await pipeline.drain_active_tasks(timeout=5.0)
    assert replies == ["done"]


@pytest.mark.asyncio
async def test_background_failure_is_retrieved_without_blocking_later_messages():
    """A raising background task must be untracked and the process keeps serving."""
    replies = []

    class ReplyingHandler(BaseMessageHandler):
        async def handle(self, message, raw_data, pipeline):
            return ReplyIntent(tier=ReplyTier.PRIMARY, text="ok")

    pipeline = PipelineHandler([ReplyingHandler()])
    calls = {"n": 0}

    async def flaky_reply(text, _message):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("reply exploded")
        replies.append(text)

    pipeline.async_reply_text = flaky_reply

    callback = CallbackMessage()
    callback.data = {"msgtype": "text", "text": {"content": "hi"}}

    status, _ = await pipeline.process(callback)
    assert status == AckMessage.STATUS_OK
    await asyncio.wait_for(pipeline.drain_active_tasks(timeout=1.0), timeout=2.0)
    assert pipeline._active_tasks == set()

    await process_and_wait(pipeline, callback)
    assert replies == ["ok"]


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
async def test_async_reply_text_returns_none_when_send_fails(monkeypatch):
    pipeline = PipelineHandler()
    monkeypatch.setattr(pipeline, "reply_text", MagicMock(return_value=None))

    incoming_msg = ChatbotMessage()
    incoming_msg.session_webhook = "https://mock.webhook"

    assert await pipeline.async_reply_text("hello", incoming_msg) is None
