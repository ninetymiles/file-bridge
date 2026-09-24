"""File downloader using DingTalk OpenAPI and streaming async HTTP."""

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import Optional
import httpx

from dingtalk_stream.utils import DINGTALK_OPENAPI_ENDPOINT


@dataclass
class DownloadResult:
    """Result of streaming file download."""
    temp_path: str
    sha256: str
    file_size: int


class FileDownloader:
    """Downloads files using DingTalk OpenAPI and streaming HTTP."""

    def __init__(
        self,
        output_dir: str,
        dingtalk_client=None,
        openapi_endpoint: str = DINGTALK_OPENAPI_ENDPOINT,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.output_dir = output_dir
        self.temp_dir = os.path.join(output_dir, ".tmp")
        self.dingtalk_client = dingtalk_client
        self.openapi_endpoint = openapi_endpoint
        self._http_client = http_client

    async def get_access_token(self) -> Optional[str]:
        """Obtain DingTalk access token from client."""
        if not self.dingtalk_client:
            return None
        return await asyncio.to_thread(self.dingtalk_client.get_access_token)

    async def get_download_url(
        self,
        download_code: str,
        robot_code: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> str:
        """Call DingTalk OpenAPI to retrieve the direct download URL."""
        if access_token is None:
            access_token = await self.get_access_token()

        if not access_token:
            raise ValueError("DingTalk access token is not available")

        if robot_code is None and self.dingtalk_client:
            robot_code = self.dingtalk_client.credential.client_id

        if not robot_code:
            raise ValueError("Robot code (client_id) is not available")

        url = f"{self.openapi_endpoint}/v1.0/robot/messageFiles/download"
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "x-acs-dingtalk-access-token": access_token,
        }
        payload = {
            "robotCode": robot_code,
            "downloadCode": download_code,
        }

        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            download_url = data.get("downloadUrl")
            if not download_url:
                raise ValueError(f"Download URL missing in response: {data}")
            return download_url
        finally:
            if owns_client:
                await client.aclose()

    async def download_file_stream(
        self,
        download_url: str,
        chunk_size: int = 64 * 1024,
    ) -> DownloadResult:
        """Stream download file content, saving to temp file while computing SHA-256."""
        os.makedirs(self.temp_dir, exist_ok=True)
        temp_file_path = os.path.join(self.temp_dir, f"file_{uuid.uuid4().hex}.tmp")

        hasher = hashlib.sha256()
        file_size = 0

        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient()
        try:
            async with client.stream("GET", download_url, follow_redirects=True) as response:
                response.raise_for_status()
                with open(temp_file_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                        if chunk:
                            hasher.update(chunk)
                            f.write(chunk)
                            file_size += len(chunk)

            return DownloadResult(
                temp_path=temp_file_path,
                sha256=hasher.hexdigest(),
                file_size=file_size,
            )
        except Exception:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            raise
        finally:
            if owns_client:
                await client.aclose()
