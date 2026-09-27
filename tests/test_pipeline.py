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


def _make_callback(data):
    callback = CallbackMessage()
    callback.headers.message_id = "m1"
    callback.data = data
    return callback


@pytest.mark.asyncio
async def test_private_text_info_summary_no_body_debug_has_content(caplog):
    pipeline = PipelineHandler()
    callback = _make_callback({
        "msgtype": "text",
        "conversationType": "1",
        "senderNick": "李四",
        "text": {"content": "你好"},
    })

    with caplog.at_level(logging.INFO):
        await pipeline.process(callback)

    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "Received private message from 李四, type=text" in m for m in info_messages
    )
    assert not any("你好" in m for m in info_messages)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await pipeline.process(callback)

    text_logs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Text content:")]
    assert text_logs == ["Text content: 你好"]


@pytest.mark.asyncio
async def test_group_richtext_info_metadata_only_debug_has_segments(caplog):
    download_code = "mIofN681YE3fFULLCODE123=="
    pipeline = PipelineHandler()
    callback = _make_callback({
        "msgtype": "richText",
        "conversationType": "2",
        "conversationTitle": "产品交流群",
        "senderNick": "张三",
        "content": {
            "richText": [
                {"text": "@文件小助手 帮我算一下"},
                {"downloadCode": download_code, "type": "picture"},
            ]
        },
    })

    with caplog.at_level(logging.INFO):
        await pipeline.process(callback)

    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    summary = [m for m in info_messages if m.startswith("Received group message")]
    assert len(summary) == 1
    assert "张三" in summary[0] and "产品交流群" in summary[0]
    assert "segments=2 (1 text, 1 picture)" in summary[0]
    # INFO must leak neither body text nor download codes.
    assert not any("帮我算一下" in m or download_code in m for m in info_messages)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await pipeline.process(callback)

    segment_logs = [r.getMessage() for r in caplog.records if "segment[" in r.getMessage()]
    assert segment_logs == [
        "RichText segment[1/2] text: @文件小助手 帮我算一下",
        f"RichText segment[2/2] picture: type=picture, downloadCode={download_code}",
    ]


@pytest.mark.asyncio
async def test_picture_info_has_no_code_debug_has_full_code(caplog):
    download_code = "PIC_FULL_CODE_456"
    pipeline = PipelineHandler()
    callback = _make_callback({
        "msgtype": "picture",
        "conversationType": "1",
        "senderNick": "王五",
        "content": {"downloadCode": download_code},
    })

    with caplog.at_level(logging.INFO):
        await pipeline.process(callback)

    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("Received private message from 王五, type=picture" in m for m in info_messages)
    assert not any(download_code in m for m in info_messages)
    # Picture callbacks carry no fileName; the summary must not invent one.
    assert not any("filename=" in m for m in info_messages)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await pipeline.process(callback)

    picture_logs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Picture attachment:")]
    assert picture_logs == [f"Picture attachment: downloadCode={download_code}"]


@pytest.mark.asyncio
async def test_file_info_summary_includes_filename(caplog):
    pipeline = PipelineHandler()
    callback = _make_callback({
        "msgtype": "file",
        "conversationType": "1",
        "senderNick": "赵六",
        "content": {"downloadCode": "FILE_CODE_789", "fileName": "Q3报表.xlsx"},
    })

    with caplog.at_level(logging.INFO):
        await pipeline.process(callback)

    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "Received private message from 赵六, type=file, filename=Q3报表.xlsx" in m
        for m in info_messages
    )
    assert not any("FILE_CODE_789" in m for m in info_messages)
