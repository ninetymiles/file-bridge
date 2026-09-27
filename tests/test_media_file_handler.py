"""Unit tests for MediaFileHandler."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from dingtalk_stream import ChatbotMessage
from lib.handlers import MediaFileHandler, PipelineHandler
from lib.file_downloader import DownloadResult


@pytest.mark.asyncio
async def test_media_file_handler_new_file(tmp_path):
    output_dir = tmp_path / "output"
    temp_file = tmp_path / "temp_file.tmp"
    temp_file.write_bytes(b"content")

    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(
        return_value=DownloadResult(
            temp_path=str(temp_file),
            sha256="dummy_sha256",
            file_size=7,
        )
    )

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.is_draining.return_value = False
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(
        output_dir=str(output_dir),
        metadata_store=mock_store,
        file_downloader=mock_downloader,
    )

    raw_data = {
        "msgtype": "file",
        "senderNick": "Alice",
        "senderId": "user_001",
        "content": {
            "downloadCode": "code_123",
            "fileName": "test_doc.pdf",
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is True

    mock_downloader.get_download_url.assert_called_once_with("code_123")
    mock_downloader.download_file_stream.assert_called_once_with("https://example.com/dl")
    mock_store.async_is_duplicate.assert_called_once_with("dummy_sha256")
    mock_store.async_insert_record.assert_called_once()
    saved_path_arg = mock_store.async_insert_record.call_args[1]["saved_path"]
    assert os.path.exists(saved_path_arg)

    # Verify reply
    mock_pipeline.async_reply_text.assert_called_once()
    reply_text = mock_pipeline.async_reply_text.call_args[0][0]
    assert "文件接收成功，已保存为:" in reply_text
    assert ".pdf" in reply_text


@pytest.mark.asyncio
async def test_media_file_handler_duplicate_file(tmp_path):
    output_dir = tmp_path / "output"
    temp_file = tmp_path / "temp_dup.tmp"
    temp_file.write_bytes(b"content")

    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(
        return_value=DownloadResult(
            temp_path=str(temp_file),
            sha256="existing_sha256",
            file_size=7,
        )
    )

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=True)
    mock_store.async_insert_record = AsyncMock()

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.is_draining.return_value = False
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(
        output_dir=str(output_dir),
        metadata_store=mock_store,
        file_downloader=mock_downloader,
    )

    raw_data = {
        "msgtype": "picture",
        "senderNick": "Bob",
        "content": {
            "downloadCode": "pic_code_123",
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is True

    # Temp file should be deleted
    assert not os.path.exists(str(temp_file))
    # No insert
    mock_store.async_insert_record.assert_not_called()
    # Replied with duplicate notice
    mock_pipeline.async_reply_text.assert_called_once_with("文件已存在，请勿重复发送", msg)


@pytest.mark.asyncio
async def test_media_file_handler_video(tmp_path):
    output_dir = tmp_path / "output"
    temp_file = tmp_path / "temp_video.tmp"
    temp_file.write_bytes(b"video bytes")

    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(
        return_value=DownloadResult(
            temp_path=str(temp_file),
            sha256="video_sha256",
            file_size=11,
        )
    )

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=2)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.is_draining.return_value = False
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(
        output_dir=str(output_dir),
        metadata_store=mock_store,
        file_downloader=mock_downloader,
    )

    raw_data = {
        "msgtype": "video",
        "senderNick": "Charlie",
        "content": {
            "downloadCode": "video_code_456",
            "fileName": "demo.mp4",
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    handled = await handler.handle(msg, raw_data, mock_pipeline)
    assert handled is True
    mock_store.async_insert_record.assert_called_once()
    reply_text = mock_pipeline.async_reply_text.call_args[0][0]
    assert ".mp4" in reply_text
