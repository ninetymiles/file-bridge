"""Unit tests for PipelineHandler and BaseMessageHandler."""

import logging

import pytest
from unittest.mock import MagicMock
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


class _EventLogHandler(logging.Handler):
    """Record application log messages into a shared event list."""

    def __init__(self, events):
        super().__init__(level=logging.INFO)
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append(("log", record.getMessage()))


def _callback(raw_data: dict) -> CallbackMessage:
    callback = CallbackMessage()
    callback.data = raw_data
    return callback


@pytest.mark.asyncio
async def test_storage_warmup_runs_before_first_info_log():
    """The storage probe must finish before the receive-summary INFO log.

    Locks the cold-disk invariant: the 3s wake timer is registered inside
    ensure_storage_ready, so it must precede the receive-summary INFO log
    (whose synchronous disk write could otherwise stall the timer).
    """
    events = []
    pipeline = PipelineHandler(logger=logging.getLogger("file-bridge"))
    pipeline.reply_text = MagicMock(return_value={"errcode": 0})
    pipeline.storage_probe = lambda: events.append(("probe", None))

    handler = _EventLogHandler(events)
    app_logger = logging.getLogger("file-bridge")
    previous_level = app_logger.level
    app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)
    try:
        await pipeline.process(
            _callback(
                {
                    "msgtype": "text",
                    "text": {"content": "hi"},
                    "senderNick": "alice",
                    "conversationType": "1",
                }
            )
        )
    finally:
        app_logger.removeHandler(handler)
        app_logger.setLevel(previous_level)

    kinds = [kind for kind, _ in events]
    assert kinds.index("probe") < kinds.index("log")
    first_log = next(message for kind, message in events if kind == "log")
    assert first_log.startswith("Received private message from alice")


@pytest.fixture
def pipeline_with_logger():
    pipeline = PipelineHandler(logger=logging.getLogger("file-bridge"))
    pipeline.reply_text = MagicMock(return_value={"errcode": 0})
    return pipeline


async def _info_messages(caplog, pipeline, raw_data) -> str:
    with caplog.at_level(logging.INFO, logger="file-bridge"):
        await pipeline.process(_callback(raw_data))
    return "\n".join(r.message for r in caplog.records if r.levelno == logging.INFO)


@pytest.mark.asyncio
async def test_received_text_includes_content_in_info(caplog, pipeline_with_logger):
    info_text = await _info_messages(
        caplog,
        pipeline_with_logger,
        {
            "msgtype": "text",
            "text": {"content": "重建索引"},
            "senderNick": "alice",
            "conversationType": "1",
        },
    )

    assert "content=重建索引" in info_text
    # downloadCode must not leak into INFO.
    assert "downloadCode" not in info_text


@pytest.mark.asyncio
async def test_received_richtext_includes_merged_content_in_info(
    caplog, pipeline_with_logger
):
    info_text = await _info_messages(
        caplog,
        pipeline_with_logger,
        {
            "msgtype": "richText",
            "content": {
                "richText": [
                    {"text": "重建索引 "},
                    {"downloadCode": "dc_pic", "type": "picture"},
                ]
            },
            "senderNick": "alice",
            "conversationType": "1",
        },
    )

    assert "content=重建索引 <img1>" in info_text
    assert "downloadCode" not in info_text


@pytest.mark.asyncio
async def test_received_richtext_picture_only_content_is_img1(
    caplog, pipeline_with_logger
):
    info_text = await _info_messages(
        caplog,
        pipeline_with_logger,
        {
            "msgtype": "richText",
            "content": {"richText": [{"downloadCode": "dc_only", "type": "picture"}]},
            "senderNick": "alice",
            "conversationType": "1",
        },
    )

    assert "content=<img1>" in info_text
    assert "downloadCode" not in info_text


@pytest.mark.asyncio
async def test_received_picture_has_no_content_field(caplog, pipeline_with_logger):
    info_text = await _info_messages(
        caplog,
        pipeline_with_logger,
        {
            "msgtype": "picture",
            "content": {"downloadCode": "dc_pic"},
            "senderNick": "alice",
            "conversationType": "1",
        },
    )

    assert "content=" not in info_text
    assert "downloadCode" not in info_text
