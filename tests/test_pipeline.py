"""Unit tests for PipelineHandler and BaseMessageHandler."""

import logging

import pytest
from unittest.mock import AsyncMock, MagicMock
from dingtalk_stream import CallbackMessage, AckMessage, ChatbotMessage
from app.handlers import BaseMessageHandler, PipelineHandler, ReplyIntent


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

    status, msg = await pipeline.process(callback)
    assert status == AckMessage.STATUS_OK
    assert msg == "OK"
    assert h1.called is True
    assert h2.called is True
    assert h3.called is True  # no short-circuit in intent-reporting chain


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
async def test_async_reply_text_logs_info_on_success(caplog):
    pipeline = PipelineHandler(logger=logging.getLogger("file-bridge"))
    pipeline.reply_text = MagicMock(return_value={"errcode": 0})

    incoming_msg = ChatbotMessage()
    incoming_msg.conversation_type = "1"
    incoming_msg.sender_nick = "alice"

    with caplog.at_level(logging.INFO, logger="file-bridge"):
        await pipeline.async_reply_text("文件接收成功", incoming_msg)

    info = "\n".join(r.message for r in caplog.records if r.levelno == logging.INFO)
    assert "Replied to private (alice): 文件接收成功" in info


@pytest.mark.asyncio
async def test_async_reply_text_logs_warning_on_failure(caplog):
    pipeline = PipelineHandler(logger=logging.getLogger("file-bridge"))
    pipeline.reply_text = MagicMock(return_value=None)

    incoming_msg = ChatbotMessage()
    incoming_msg.conversation_type = "2"
    incoming_msg.conversation_title = "dev group"

    with caplog.at_level(logging.WARNING, logger="file-bridge"):
        result = await pipeline.async_reply_text("正在唤醒存储服务，请稍候…", incoming_msg)

    assert result is None
    warnings = "\n".join(r.message for r in caplog.records if r.levelno == logging.WARNING)
    assert "Reply failed to group (dev group): 正在唤醒存储服务" in warnings


@pytest.mark.asyncio
async def test_async_reply_text_sends_before_logging():
    """The DingTalk send must happen before the local INFO log write.

    Guards the warmup path: while the storage probe wakes a cold disk, a
    synchronous local log I/O must not delay the user-facing notice.
    """
    pipeline = PipelineHandler()
    order = MagicMock()
    order.attach_mock(MagicMock(return_value={"errcode": 0}), "reply")
    order.attach_mock(MagicMock(), "info")
    pipeline.reply_text = order.reply
    pipeline.logger = MagicMock()
    pipeline.logger.info = order.info

    incoming_msg = ChatbotMessage()
    incoming_msg.conversation_type = "1"
    incoming_msg.sender_nick = "alice"

    await pipeline.async_reply_text("正在唤醒存储服务，请稍候…", incoming_msg)

    call_names = [c[0] for c in order.mock_calls]
    assert call_names.index("reply") < call_names.index("info")


@pytest.mark.asyncio
async def test_dispatch_runs_storage_warmup_before_first_info_log(monkeypatch):
    """ensure_storage_ready must run before any INFO log in the chain.

    Locks the cold-disk invariant: the 3s wake timer is registered inside
    ensure_storage_ready, so it must precede the receive-summary INFO log
    (whose synchronous disk write could otherwise stall the timer).
    """
    pipeline = PipelineHandler()
    order = MagicMock()
    order.attach_mock(AsyncMock(), "warmup")
    order.attach_mock(MagicMock(), "log_received")

    import app.handlers.message as message_mod
    pipeline.storage_probe = MagicMock()
    monkeypatch.setattr(message_mod, "ensure_storage_ready", order.warmup)
    pipeline._log_received_message = order.log_received

    callback = CallbackMessage()
    callback.data = {"msgtype": "text", "text": {"content": "hi"}, "conversationType": "1"}

    await pipeline._dispatch(callback)

    call_names = [c[0] for c in order.mock_calls]
    assert call_names.index("warmup") < call_names.index("log_received")


@pytest.fixture
def pipeline_with_logger():
    return PipelineHandler(logger=logging.getLogger("file-bridge"))


def test_received_text_includes_content_in_info(caplog, pipeline_with_logger):
    raw_data = {
        "msgtype": "text",
        "text": {"content": "重建索引"},
        "senderNick": "alice",
        "conversationType": "1",
    }
    message = ChatbotMessage.from_dict(raw_data)
    with caplog.at_level(logging.INFO, logger="file-bridge"):
        pipeline_with_logger._log_received_message(message, raw_data)
    info_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.INFO)
    assert "content=重建索引" in info_text
    # downloadCode must not leak into INFO.
    assert "downloadCode" not in info_text


def test_received_richtext_includes_merged_content_in_info(caplog, pipeline_with_logger):
    raw_data = {
        "msgtype": "richText",
        "content": {
            "richText": [
                {"text": "重建索引 "},
                {"downloadCode": "dc_pic", "type": "picture"},
            ]
        },
        "senderNick": "alice",
        "conversationType": "1",
    }
    message = ChatbotMessage.from_dict(raw_data)
    with caplog.at_level(logging.INFO, logger="file-bridge"):
        pipeline_with_logger._log_received_message(message, raw_data)
    info_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.INFO)
    assert "content=重建索引 <img1>" in info_text
    assert "downloadCode" not in info_text


def test_received_richtext_picture_only_content_is_img1(caplog, pipeline_with_logger):
    raw_data = {
        "msgtype": "richText",
        "content": {"richText": [{"downloadCode": "dc_only", "type": "picture"}]},
        "senderNick": "alice",
        "conversationType": "1",
    }
    message = ChatbotMessage.from_dict(raw_data)
    with caplog.at_level(logging.INFO, logger="file-bridge"):
        pipeline_with_logger._log_received_message(message, raw_data)
    info_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.INFO)
    assert "content=<img1>" in info_text
    assert "downloadCode" not in info_text


def test_received_picture_has_no_content_field(caplog, pipeline_with_logger):
    raw_data = {
        "msgtype": "picture",
        "content": {"downloadCode": "dc_pic"},
        "senderNick": "alice",
        "conversationType": "1",
    }
    message = ChatbotMessage.from_dict(raw_data)
    with caplog.at_level(logging.INFO, logger="file-bridge"):
        pipeline_with_logger._log_received_message(message, raw_data)
    info_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.INFO)
    assert "content=" not in info_text
    assert "downloadCode" not in info_text
