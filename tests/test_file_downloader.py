"""Unit tests for FileDownloader."""

import hashlib
import logging
import os
import pytest
import httpx
from app.services.file_downloader import FileDownloader, mask_access_token


@pytest.mark.asyncio
async def test_get_download_url(tmp_path):
    async def mock_handler(request: httpx.Request):
        if request.url.path == "/v1.0/robot/messageFiles/download":
            headers = request.headers
            assert headers["x-acs-dingtalk-access-token"] == "test_token"
            assert request.content is not None
            return httpx.Response(200, json={"downloadUrl": "https://download.example.com/file123"})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        downloader = FileDownloader(
            output_dir=str(tmp_path),
            openapi_endpoint="https://mock.dingtalk.com",
            http_client=http_client,
        )

        url = await downloader.get_download_url(
            download_code="code_abc_123",
            robot_code="robot_xyz",
            access_token="test_token",
        )
        assert url == "https://download.example.com/file123"


@pytest.mark.asyncio
async def test_resolve_url_debug_logs_full_code_and_url_masked_token(tmp_path, caplog):
    async def mock_handler(request: httpx.Request):
        return httpx.Response(200, json={"downloadUrl": "https://download.example.com/signed?sig=abc"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        downloader = FileDownloader(
            output_dir=str(tmp_path),
            openapi_endpoint="https://mock.dingtalk.com",
            http_client=http_client,
        )

        with caplog.at_level(logging.DEBUG, logger="file-bridge.downloader"):
            await downloader.get_download_url(
                download_code="FULL_DOWNLOAD_CODE_1",
                robot_code="robot_xyz",
                access_token="test_token",
            )

    text = caplog.text
    assert "FULL_DOWNLOAD_CODE_1" in text
    assert "https://download.example.com/signed?sig=abc" in text
    # The root credential must never appear verbatim; only its fingerprint.
    assert "test_token" not in text
    assert mask_access_token("test_token") == "test_t...en"
    assert "test_t...en" in text


@pytest.mark.asyncio
async def test_resolve_url_info_level_hides_codes_and_url(tmp_path, caplog):
    async def mock_handler(request: httpx.Request):
        return httpx.Response(200, json={"downloadUrl": "https://download.example.com/signed"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        downloader = FileDownloader(
            output_dir=str(tmp_path),
            openapi_endpoint="https://mock.dingtalk.com",
            http_client=http_client,
        )

        with caplog.at_level(logging.INFO, logger="file-bridge.downloader"):
            await downloader.get_download_url(
                download_code="FULL_DOWNLOAD_CODE_2",
                robot_code="robot_xyz",
                access_token="test_token",
            )

    assert "FULL_DOWNLOAD_CODE_2" not in caplog.text
    assert "download.example.com" not in caplog.text
    assert "test_token" not in caplog.text


@pytest.mark.asyncio
async def test_resolve_url_failure_logs_status_and_body_then_raises(tmp_path, caplog):
    async def mock_handler(request: httpx.Request):
        return httpx.Response(400, json={"code": "invalidParameter.robotCode.downloadCode"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        downloader = FileDownloader(
            output_dir=str(tmp_path),
            openapi_endpoint="https://mock.dingtalk.com",
            http_client=http_client,
        )

        with caplog.at_level(logging.DEBUG, logger="file-bridge.downloader"):
            with pytest.raises(httpx.HTTPStatusError):
                await downloader.get_download_url(
                    download_code="EXPIRED_CODE",
                    robot_code="robot_xyz",
                    access_token="test_token",
                )

    error_logs = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("messageFiles/download failed: status=400" in m for m in error_logs)
    assert any("invalidParameter.robotCode.downloadCode" in m for m in error_logs)


def test_mask_access_token_variants():
    assert mask_access_token("abcdef1234XY") == "abcdef...XY"
    assert mask_access_token("") == "unavailable"
    assert mask_access_token(None) == "unavailable"
    assert mask_access_token("short") == "***"


@pytest.mark.asyncio
async def test_download_file_stream(tmp_path, caplog):
    test_content = b"Large chunk of binary data for stream testing" * 1000
    expected_sha256 = hashlib.sha256(test_content).hexdigest()
    expected_size = len(test_content)

    async def mock_handler(request: httpx.Request):
        if request.url == "https://download.example.com/stream-file":
            return httpx.Response(200, content=test_content)
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        downloader = FileDownloader(
            output_dir=str(tmp_path),
            http_client=http_client,
        )

        with caplog.at_level(logging.DEBUG, logger="file-bridge.downloader"):
            result = await downloader.download_file_stream("https://download.example.com/stream-file")
        assert result.sha256 == expected_sha256
        assert result.file_size == expected_size
        assert os.path.exists(result.temp_path)

        with open(result.temp_path, "rb") as f:
            assert f.read() == test_content

    complete_logs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Streamed download complete")]
    assert len(complete_logs) == 1
    assert f"{expected_size} bytes" in complete_logs[0]
    assert result.temp_path in complete_logs[0]
