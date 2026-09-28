"""End-to-end integration tests for the message pipeline and app entrypoint."""

import os
import hashlib
import pytest
from unittest.mock import MagicMock, AsyncMock
import httpx
from dingtalk_stream import CallbackMessage, AckMessage
from app.main import create_pipeline
from app.services.metadata_store import MetadataStore


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
    pipeline = create_pipeline(str(output_dir), metadata_store, mock_client)
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

    await http_client.aclose()
