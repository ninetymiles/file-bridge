"""Unit tests for MediaFileHandler."""

import logging
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dingtalk_stream import ChatbotMessage
from app.handlers import MediaFileHandler, PipelineHandler, ReplyTier
from app.services.file_downloader import DownloadResult


def _unsupported_type_handler():
    return MediaFileHandler(
        output_dir=".",
        metadata_store=MagicMock(),
        file_downloader=MagicMock(),
    )

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

    intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is not None
    assert intent.tier == ReplyTier.PRIMARY

    mock_downloader.get_download_url.assert_called_once_with("code_123")
    mock_downloader.download_file_stream.assert_called_once_with("https://example.com/dl")
    mock_store.async_is_duplicate.assert_called_once_with("dummy_sha256")
    mock_store.async_insert_record.assert_called_once()
    saved_path_arg = mock_store.async_insert_record.call_args[1]["saved_path"]
    assert os.path.exists(saved_path_arg)

    # Verify reply
    mock_pipeline.async_reply_text.assert_not_called()
    assert "文件接收成功，已保存为:" in intent.text
    assert ".pdf" in intent.text


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

    intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is not None
    assert intent.tier == ReplyTier.PRIMARY

    # Temp file should be deleted
    assert not os.path.exists(str(temp_file))
    # No insert
    mock_store.async_insert_record.assert_not_called()
    mock_pipeline.async_reply_text.assert_not_called()
    assert intent.text == "文件已存在，请勿重复发送"


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

    intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is not None
    assert intent.tier == ReplyTier.PRIMARY
    mock_store.async_insert_record.assert_called_once()
    mock_pipeline.async_reply_text.assert_not_called()
    assert ".mp4" in intent.text


@pytest.mark.asyncio
async def test_rich_text_single_image(tmp_path):
    output_dir = tmp_path / "output"
    temp_file = tmp_path / "temp_pic.tmp"
    temp_file.write_bytes(b"pic1")

    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(
        return_value=DownloadResult(temp_path=str(temp_file), sha256="sha_pic1", file_size=4)
    )

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.is_draining.return_value = False
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir=str(output_dir), metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "richText",
        "senderNick": "Alice",
        "senderId": "user_001",
        "content": {
            "richText": [
                {"text": "@FileBridge"},
                {"text": "abcd"},
                {"type": "picture", "downloadCode": "code_1"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is not None
    assert intent.tier == ReplyTier.PRIMARY

    mock_store.async_insert_record.assert_called_once()
    mock_pipeline.async_reply_text.assert_not_called()
    assert "文件接收成功，已保存为:" in intent.text


@pytest.mark.asyncio
async def test_rich_text_multiple_images(tmp_path, caplog):
    output_dir = tmp_path / "output"
    temp1 = tmp_path / "t1.tmp"
    temp1.write_bytes(b"pic1")
    temp2 = tmp_path / "t2.tmp"
    temp2.write_bytes(b"pic2")

    results = [
        DownloadResult(temp_path=str(temp1), sha256="sha1", file_size=4),
        DownloadResult(temp_path=str(temp2), sha256="sha2", file_size=4),
    ]
    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(side_effect=results)

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.is_draining.return_value = False
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir=str(output_dir), metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "richText",
        "senderNick": "Alice",
        "senderId": "user_001",
        "content": {
            "richText": [
                {"text": "@FileBridge"},
                {"type": "picture", "downloadCode": "code_1"},
                {"text": "\n"},
                {"type": "picture", "downloadCode": "code_2"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    with caplog.at_level(logging.INFO):
        intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is not None
    assert intent.tier == ReplyTier.PRIMARY

    assert mock_store.async_insert_record.call_count == 2
    mock_pipeline.async_reply_text.assert_not_called()
    lines = intent.text.split("\n")
    assert len(lines) == 2
    assert all("文件接收成功，已保存为:" in line for line in lines)

    # Each picture emits exactly one download-start INFO line; codes stay out.
    downloading = [
        r.message for r in caplog.records
        if r.levelno == logging.INFO and r.message.startswith("Downloading file:")
    ]
    assert len(downloading) == 2
    assert all("code_1" not in m and "code_2" not in m for m in downloading)


@pytest.mark.asyncio
async def test_rich_text_with_duplicate(tmp_path):
    output_dir = tmp_path / "output"
    temp1 = tmp_path / "t1.tmp"
    temp1.write_bytes(b"pic1")
    temp2 = tmp_path / "t2.tmp"
    temp2.write_bytes(b"pic2")

    results = [
        DownloadResult(temp_path=str(temp1), sha256="sha1", file_size=4),
        DownloadResult(temp_path=str(temp2), sha256="sha2", file_size=4),
    ]
    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(side_effect=results)

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(side_effect=[True, False])
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.is_draining.return_value = False
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir=str(output_dir), metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "richText",
        "senderNick": "Alice",
        "senderId": "user_001",
        "content": {
            "richText": [
                {"type": "picture", "downloadCode": "code_1"},
                {"type": "picture", "downloadCode": "code_2"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is not None
    assert intent.tier == ReplyTier.PRIMARY

    mock_pipeline.async_reply_text.assert_not_called()
    lines = intent.text.split("\n")
    assert "文件已存在，请勿重复发送" in lines[0]
    assert "文件接收成功，已保存为:" in lines[1]


@pytest.mark.asyncio
async def test_rich_text_no_picture_segments():
    mock_downloader = MagicMock()
    mock_store = MagicMock()
    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir="/tmp", metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "richText",
        "content": {
            "richText": [
                {"text": "hello"},
                {"text": "\n"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is None
    mock_pipeline.async_reply_text.assert_not_called()
    mock_downloader.get_download_url.assert_not_called()


@pytest.mark.asyncio
async def test_rich_text_partial_failure(tmp_path):
    output_dir = tmp_path / "output"
    temp2 = tmp_path / "t2.tmp"
    temp2.write_bytes(b"pic2")

    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    # First download raises, second succeeds
    mock_downloader.download_file_stream = AsyncMock(
        side_effect=[RuntimeError("download failed"), DownloadResult(temp_path=str(temp2), sha256="sha2", file_size=4)]
    )

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.is_draining.return_value = False
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir=str(output_dir), metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "richText",
        "senderNick": "Alice",
        "senderId": "user_001",
        "content": {
            "richText": [
                {"type": "picture", "downloadCode": "code_1"},
                {"type": "picture", "downloadCode": "code_2"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    intent = await handler.handle(msg, raw_data, mock_pipeline)
    assert intent is not None
    assert intent.tier == ReplyTier.PRIMARY

    # Second image still saved despite first failure
    mock_store.async_insert_record.assert_called_once()
    mock_pipeline.async_reply_text.assert_not_called()
    lines = intent.text.split("\n")
    assert "文件接收处理失败，请稍后重试" in lines[0]
    assert "文件接收成功，已保存为:" in lines[1]


@pytest.mark.asyncio
async def test_media_file_handler_single_chat_audio_returns_none():
    """audio is not a media type; handler returns None (dispatcher handles fallback)."""
    handler = _unsupported_type_handler()
    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    raw_data = {
        "msgtype": "audio",
        "conversationType": "1",
        "content": {"downloadCode": "code_audio", "duration": 1000},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    intent = await handler.handle(msg, raw_data, mock_pipeline)

    assert intent is None
    mock_pipeline.async_reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_file_handler_unknown_type_returns_none():
    handler = _unsupported_type_handler()
    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    raw_data = {"msgtype": "sticker", "conversationType": "1"}
    msg = ChatbotMessage.from_dict(raw_data)

    intent = await handler.handle(msg, raw_data, mock_pipeline)

    assert intent is None
    mock_pipeline.async_reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_file_handler_group_unknown_type_stays_silent():
    handler = _unsupported_type_handler()
    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    raw_data = {
        "msgtype": "audio",
        "conversationType": "2",
        "content": {"downloadCode": "code_audio"},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    intent = await handler.handle(msg, raw_data, mock_pipeline)

    assert intent is None
    mock_pipeline.async_reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_media_reply_includes_metadata_line(tmp_path):
    output_dir = tmp_path / "output"
    temp_file = tmp_path / "temp_video.tmp"
    temp_file.write_bytes(b"video bytes")

    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(
        return_value=DownloadResult(temp_path=str(temp_file), sha256="v_sha", file_size=11)
    )

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir=str(output_dir), metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "video",
        "senderNick": "Charlie",
        "content": {"downloadCode": "vc", "fileName": "demo.mp4"},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    with patch("app.handlers.message.extract_media_metadata", return_value="544x960  30.2fps"):
        intent = await handler.handle(msg, raw_data, mock_pipeline)

    mock_pipeline.async_reply_text.assert_not_called()
    lines = intent.text.split("\n")
    assert lines[0].startswith("文件接收成功，已保存为:")
    assert lines[1] == "544x960  30.2fps"


@pytest.mark.asyncio
async def test_single_media_reply_no_metadata_stays_filename_only(tmp_path):
    output_dir = tmp_path / "output"
    temp_file = tmp_path / "temp_pic.tmp"
    temp_file.write_bytes(b"pic bytes")

    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(
        return_value=DownloadResult(temp_path=str(temp_file), sha256="p_sha", file_size=9)
    )

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir=str(output_dir), metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "picture",
        "senderNick": "Alice",
        "content": {"downloadCode": "pc"},
    }
    msg = ChatbotMessage.from_dict(raw_data)

    with patch("app.handlers.message.extract_media_metadata", return_value=None):
        intent = await handler.handle(msg, raw_data, mock_pipeline)

    mock_pipeline.async_reply_text.assert_not_called()
    assert intent.text.startswith("文件接收成功，已保存为:")
    assert "\n" not in intent.text  # no metadata line appended


@pytest.mark.asyncio
async def test_rich_text_reply_appends_per_image_metadata(tmp_path):
    output_dir = tmp_path / "output"
    temp1 = tmp_path / "t1.tmp"
    temp1.write_bytes(b"pic1")
    temp2 = tmp_path / "t2.tmp"
    temp2.write_bytes(b"pic2")

    results = [
        DownloadResult(temp_path=str(temp1), sha256="sha1", file_size=4),
        DownloadResult(temp_path=str(temp2), sha256="sha2", file_size=4),
    ]
    mock_downloader = MagicMock()
    mock_downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    mock_downloader.download_file_stream = AsyncMock(side_effect=results)

    mock_store = MagicMock()
    mock_store.async_is_duplicate = AsyncMock(return_value=False)
    mock_store.async_insert_record = AsyncMock(return_value=1)

    mock_pipeline = MagicMock(spec=PipelineHandler)
    mock_pipeline.async_reply_text = AsyncMock()

    handler = MediaFileHandler(output_dir=str(output_dir), metadata_store=mock_store, file_downloader=mock_downloader)

    raw_data = {
        "msgtype": "richText",
        "content": {
            "richText": [
                {"type": "picture", "downloadCode": "code_1"},
                {"type": "picture", "downloadCode": "code_2"},
            ]
        },
    }
    msg = ChatbotMessage.from_dict(raw_data)

    # First image has metadata, second has none.
    with patch(
        "app.handlers.message.extract_media_metadata",
        side_effect=["2024-01-15 14:30:00  f/2.8  ISO 400", None],
    ):
        intent = await handler.handle(msg, raw_data, mock_pipeline)

    mock_pipeline.async_reply_text.assert_not_called()
    lines = intent.text.split("\n")
    # Three lines: filename1, metadata1, filename2 (no metadata)
    assert len(lines) == 3
    assert lines[0].startswith("文件接收成功，已保存为:")
    assert lines[1] == "2024-01-15 14:30:00  f/2.8  ISO 400"
    assert lines[2].startswith("文件接收成功，已保存为:")
