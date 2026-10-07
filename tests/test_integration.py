"""End-to-end integration tests for the message pipeline and app entrypoint."""

import functools
import logging
import os
import hashlib
import time
import pytest
from unittest.mock import MagicMock, AsyncMock
import httpx
from dingtalk_stream import CallbackMessage, AckMessage
import app.handlers.message as message_module
from app.main import create_pipeline, setup_logger
from app.services.command_matching import SubstringCommandMatcher
from app.services.disk_warmup import ensure_storage_ready
from app.services.metadata_store import MetadataStore
from app.handlers.message import (
    CAPABILITY_VARIANTS,
    STORAGE_UNAVAILABLE_TEXT,
    WAKING_STORAGE_TEXT,
)


@pytest.mark.asyncio
async def test_end_to_end_file_and_rebuild_index_pipeline(tmp_path):
    output_dir = tmp_path / "e2e_output"
    file_bytes = b"Hello, integration test file content!"
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Mock OpenAPI download URL endpoint and file downloading
    async def mock_handler(request: httpx.Request):
        if request.url.path == "/v1.0/robot/messageFiles/download":
            return httpx.Response(200, json={"downloadUrl": "https://mock.dl/file1"})
        elif str(request.url) == "https://mock.dl/file1":
            return httpx.Response(200, content=file_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    # Mock dingtalk client
    mock_client = MagicMock()
    mock_client.credential.client_id = "test_robot"
    mock_client.get_access_token = MagicMock(return_value="mock_access_token")

    metadata_store = MetadataStore(output_dir=str(output_dir))
    pipeline = create_pipeline(
        str(output_dir), metadata_store, mock_client, SubstringCommandMatcher()
    )
    # Inject test http_client
    for handler in pipeline.handlers:
        if hasattr(handler, "file_downloader"):
            handler.file_downloader._http_client = http_client

    # Mock reply_text on pipeline to capture replies
    replies = []

    def fake_reply_text(text, msg):
        replies.append((text, msg))
        return {"errcode": 0}

    pipeline.reply_text = fake_reply_text

    # 1. Send media file message for the first time
    cb_msg1 = CallbackMessage()
    cb_msg1.data = {
        "msgtype": "file",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "content": {
            "downloadCode": "code_e2e_1",
            "fileName": "sample.pdf",
        },
    }

    status, msg = await pipeline.process(cb_msg1)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 1
    assert "文件接收成功，已保存为:" in replies[0][0]
    assert ".pdf" in replies[0][0]

    # Verify SQLite record created
    metadata_store = next(h.metadata_store for h in pipeline.handlers if hasattr(h, "metadata_store"))
    assert metadata_store.is_duplicate(file_sha256) is True

    # 2. Send the exact same file again (deduplication check)
    cb_msg2 = CallbackMessage()
    cb_msg2.data = {
        "msgtype": "file",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "content": {
            "downloadCode": "code_e2e_1",
            "fileName": "sample.pdf",
        },
    }

    status, msg = await pipeline.process(cb_msg2)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 2
    assert replies[1][0] == "文件已存在，请勿重复发送"

    # 3. Simulate disk file removal (e.g. archiving)
    with metadata_store.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT saved_path FROM file_metadata WHERE sha256 = ?", (file_sha256,))
        saved_path = cursor.fetchone()["saved_path"]

    assert os.path.exists(saved_path)
    os.remove(saved_path)

    # 4. Send '重建索引' text command
    cb_msg3 = CallbackMessage()
    cb_msg3.data = {
        "msgtype": "text",
        "senderNick": "Admin",
        "sessionWebhook": "https://webhook.mock",
        "text": {"content": "重建索引"},
    }

    status, msg = await pipeline.process(cb_msg3)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 3
    assert "索引重建完成，清理元数据 1 条，现有有效索引 0 条。" in replies[2][0]

    # 5. Send richText with both image and command — both must fire
    cb_msg4 = CallbackMessage()
    cb_msg4.data = {
        "msgtype": "richText",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "content": {
            "richText": [
                {"text": "@FileBridge"},
                {"text": "重建索引 "},
                {"type": "picture", "downloadCode": "code_rich_1"},
            ]
        },
    }

    status, msg = await pipeline.process(cb_msg4)
    assert status == AckMessage.STATUS_OK
    # One merged reply: PRIMARY tier wins, command result + image save result merged
    assert len(replies) == 4
    assert "索引重建完成" in replies[3][0]
    assert "文件接收成功，已保存为:" in replies[3][0]

    # 6. Single-chat text unmatched: only one SECONDARY guidance reply
    cb_msg5 = CallbackMessage()
    cb_msg5.data = {
        "msgtype": "text",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "text": {"content": "hello world"},
    }

    status, msg = await pipeline.process(cb_msg5)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 5
    # Guidance reply contract: a single message whose capability list has
    # exactly four bullets. Wording variants are randomized by build_guide_reply
    # and covered deterministically in test_command_handler, so this integration
    # assertion must not pin any specific variant's literal text.
    guide = replies[4][0]
    assert guide.count("• ") == len(CAPABILITY_VARIANTS)

    # 7. richText with picture but no command: only media save result, no guidance
    cb_msg6 = CallbackMessage()
    cb_msg6.data = {
        "msgtype": "richText",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "content": {
            "richText": [
                {"text": "@FileBridge"},
                {"text": "abcd"},
                {"type": "picture", "downloadCode": "code_rich_2"},
            ]
        },
    }

    status, msg = await pipeline.process(cb_msg6)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 6
    assert "文件已存在，请勿重复发送" in replies[5][0] or "文件接收成功，已保存为:" in replies[5][0]
    assert "我可以帮您" not in replies[5][0]

    # 8. Single-chat audio: explicit unsupported reply
    cb_msg7 = CallbackMessage()
    cb_msg7.data = {
        "msgtype": "audio",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "conversationType": "1",
        "content": {"downloadCode": "code_audio", "duration": 1000},
    }

    status, msg = await pipeline.process(cb_msg7)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 7
    assert "语音消息" in replies[6][0] and "不支持" in replies[6][0]

    # 9. Single-chat unknown type: explicit unsupported reply
    cb_msg8 = CallbackMessage()
    cb_msg8.data = {
        "msgtype": "sticker",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "conversationType": "1",
    }

    status, msg = await pipeline.process(cb_msg8)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 8
    assert "不支持" in replies[7][0]

    # 10. Single-chat picture without downloadCode: unsupported reply
    cb_msg9 = CallbackMessage()
    cb_msg9.data = {
        "msgtype": "picture",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "conversationType": "1",
        "content": {},
    }

    status, msg = await pipeline.process(cb_msg9)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 9
    assert "不支持" in replies[8][0]

    # 11. Group message with no intents: silent ACK (audio in group)
    cb_msg10 = CallbackMessage()
    cb_msg10.data = {
        "msgtype": "audio",
        "senderNick": "Tester",
        "senderId": "user_100",
        "sessionWebhook": "https://webhook.mock",
        "conversationType": "2",
        "content": {"downloadCode": "code_audio"},
    }

    status, msg = await pipeline.process(cb_msg10)
    assert status == AckMessage.STATUS_OK
    assert len(replies) == 9  # no new reply

    await http_client.aclose()


# ---------------------------------------------------------------------------
# Storage warmup (Dispatcher entry) composition tests
# ---------------------------------------------------------------------------


@pytest.fixture
def short_warmup_delay(monkeypatch):
    """Compress the 3s warmup timer while keeping the real race logic."""
    monkeypatch.setattr(
        message_module,
        "ensure_storage_ready",
        functools.partial(ensure_storage_ready, delay=0.05),
    )


def _build_warmup_pipeline(tmp_path):
    """Assemble the real pipeline on a tmp output dir; replies are captured."""
    output_dir = tmp_path / "warmup_output"
    mock_client = MagicMock()
    mock_client.credential.client_id = "test_robot"
    mock_client.get_access_token = MagicMock(return_value="mock_access_token")
    metadata_store = MetadataStore(output_dir=str(output_dir))
    pipeline = create_pipeline(
        str(output_dir), metadata_store, mock_client, SubstringCommandMatcher()
    )
    replies = []

    def fake_reply_text(text, msg):
        replies.append(text)
        return {"errcode": 0}

    pipeline.reply_text = fake_reply_text
    return pipeline, output_dir, replies


def _send(pipeline, data):
    callback = CallbackMessage()
    callback.data = data
    return pipeline.process(callback)


_BASE_DATA = {
    "senderNick": "Tester",
    "senderId": "user_100",
    "sessionWebhook": "https://webhook.mock",
    "conversationType": "1",
}


@pytest.mark.asyncio
async def test_slow_probe_sends_waking_notice_before_logs_and_final_reply(
    tmp_path, short_warmup_delay
):
    pipeline, _, replies = _build_warmup_pipeline(tmp_path)
    events = []

    def slow_probe():
        time.sleep(0.2)
        events.append("probe_done")

    pipeline.storage_probe = slow_probe

    original_log = pipeline._log_received_message

    def log_spy(message, raw_data):
        events.append("log_received")
        return original_log(message, raw_data)

    pipeline._log_received_message = log_spy

    base_reply = pipeline.reply_text

    def timed_reply(text, msg):
        events.append(("reply", text))
        return base_reply(text, msg)

    pipeline.reply_text = timed_reply

    status, _ = await _send(pipeline, {
        **_BASE_DATA,
        "msgtype": "text",
        "text": {"content": "你好"},
    })

    assert status == AckMessage.STATUS_OK
    assert len(replies) == 2
    assert replies[0] == WAKING_STORAGE_TEXT
    # Final reply is the regular unmatched-command guidance.
    assert replies[1].count("• ") == len(CAPABILITY_VARIANTS)

    # Order: notice -> probe completion -> first receive log -> final reply.
    assert events[0] == ("reply", WAKING_STORAGE_TEXT)
    assert events[1] == "probe_done"
    assert events[2] == "log_received"
    assert events[3][0] == "reply"


@pytest.mark.asyncio
async def test_fast_probe_is_silent_and_touches_activity_file(tmp_path):
    # Keeps the real probe bound by create_pipeline (write_activity_file).
    pipeline, output_dir, replies = _build_warmup_pipeline(tmp_path)

    status, _ = await _send(pipeline, {
        **_BASE_DATA,
        "msgtype": "text",
        "text": {"content": "你好"},
    })

    assert status == AckMessage.STATUS_OK
    assert len(replies) == 1
    assert replies[0] != WAKING_STORAGE_TEXT
    assert os.path.exists(output_dir / ".activity")


@pytest.mark.asyncio
async def test_probe_failure_replies_unavailable_and_skips_pipeline(tmp_path):
    pipeline, _, replies = _build_warmup_pipeline(tmp_path)

    def broken_probe():
        raise OSError("volume unreachable")

    pipeline.storage_probe = broken_probe

    log_calls = []
    pipeline._log_received_message = lambda message, raw_data: log_calls.append(1)

    status, _ = await _send(pipeline, {
        **_BASE_DATA,
        "msgtype": "text",
        "text": {"content": "重建索引"},
    })

    assert status == AckMessage.STATUS_OK
    assert replies == [STORAGE_UNAVAILABLE_TEXT]
    assert log_calls == []


@pytest.mark.asyncio
async def test_every_message_type_warms_up_before_processing(tmp_path):
    pipeline, _, replies = _build_warmup_pipeline(tmp_path)
    events = []

    def recording_probe():
        events.append("probe")

    pipeline.storage_probe = recording_probe

    async def mock_download(request: httpx.Request):
        if request.url.path == "/v1.0/robot/messageFiles/download":
            events.append("download")
            return httpx.Response(200, json={"downloadUrl": "https://mock.dl/x"})
        # Distinct bytes per download so dedupe never fires.
        return httpx.Response(200, content=b"payload-" + str(len(events)).encode())

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_download))
    for handler in pipeline.handlers:
        if hasattr(handler, "file_downloader"):
            handler.file_downloader._http_client = http_client

    messages = [
        {"msgtype": "text", "text": {"content": "你好"}},
        {"msgtype": "picture", "content": {"downloadCode": "code_pic"}},
        {
            "msgtype": "file",
            "content": {"downloadCode": "code_file", "fileName": "a.pdf"},
        },
        {
            "msgtype": "richText",
            "content": {
                "richText": [
                    {"text": "@FileBridge"},
                    {"type": "picture", "downloadCode": "code_rich"},
                ]
            },
        },
        {"msgtype": "audio", "content": {"downloadCode": "code_audio", "duration": 1000}},
    ]

    for data in messages:
        before = len(events)
        status, _ = await _send(pipeline, {**_BASE_DATA, **data})
        assert status == AckMessage.STATUS_OK
        segment = events[before:]
        # Exactly one probe per message, and it runs before any handler work.
        assert segment[0] == "probe"
        assert segment.count("probe") == 1

    await http_client.aclose()


@pytest.mark.asyncio
async def test_cold_disk_rebuild_command_replies_waking_then_result(
    tmp_path, short_warmup_delay
):
    pipeline, _, replies = _build_warmup_pipeline(tmp_path)

    def slow_probe():
        time.sleep(0.2)

    pipeline.storage_probe = slow_probe

    status, _ = await _send(pipeline, {
        **_BASE_DATA,
        "msgtype": "text",
        "text": {"content": "重建索引"},
    })

    assert status == AckMessage.STATUS_OK
    assert len(replies) == 2
    assert replies[0] == WAKING_STORAGE_TEXT
    assert replies[1].startswith("索引重建完成")


@pytest.mark.asyncio
async def test_media_pipeline_emits_no_httpx_request_lines_at_info(tmp_path, caplog):
    """After setup_logger, httpx per-request INFO lines must not appear.

    httpx logs "HTTP Request: ..." at INFO by default; those lines carry
    signed OSS URLs. setup_logger pins the httpx logger to WARNING so a
    default INFO run stays clean.
    """
    setup_logger("INFO")

    file_bytes = b"integration media payload"

    async def mock_handler(request: httpx.Request):
        if request.url.path == "/v1.0/robot/messageFiles/download":
            return httpx.Response(200, json={"downloadUrl": "https://mock.dl/f"})
        if str(request.url) == "https://mock.dl/f":
            return httpx.Response(200, content=file_bytes)
        return httpx.Response(404)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    mock_client = MagicMock()
    mock_client.credential.client_id = "test_robot"
    mock_client.get_access_token = MagicMock(return_value="tok")

    metadata_store = MetadataStore(output_dir=str(tmp_path / "out"))
    pipeline = create_pipeline(
        str(tmp_path / "out"), metadata_store, mock_client, SubstringCommandMatcher()
    )
    for handler in pipeline.handlers:
        if hasattr(handler, "file_downloader"):
            handler.file_downloader._http_client = http_client
    pipeline.reply_text = MagicMock(return_value={"errcode": 0})

    cb = CallbackMessage()
    cb.data = {
        "msgtype": "file",
        "senderNick": "Tester",
        "senderId": "user_1",
        "sessionWebhook": "https://webhook.mock",
        "content": {"downloadCode": "code_x", "fileName": "a.pdf"},
    }

    with caplog.at_level(logging.INFO):
        status, _ = await pipeline.process(cb)

    assert status == AckMessage.STATUS_OK
    info_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.INFO)
    assert "HTTP Request:" not in info_text
    # Application-level download/save INFO lines are still present.
    assert "Downloading file:" in info_text

    await http_client.aclose()
