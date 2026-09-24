"""Unit tests for FileDownloader."""

import hashlib
import os
import pytest
import httpx
from lib.file_downloader import FileDownloader


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
async def test_download_file_stream(tmp_path):
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

        result = await downloader.download_file_stream("https://download.example.com/stream-file")
        assert result.sha256 == expected_sha256
        assert result.file_size == expected_size
        assert os.path.exists(result.temp_path)

        with open(result.temp_path, "rb") as f:
            assert f.read() == test_content
