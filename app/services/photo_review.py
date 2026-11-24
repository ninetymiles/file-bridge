"""Aesthetic photo review through an OpenAI-compatible vision gateway.

The service encodes a local photo into a JPEG data URI, asks the gateway for an
aesthetic analysis plus praise, and returns the text. Configuration is injected
by the caller (this module never reads the process environment), and every
failure degrades to "no review" so a save-and-reply flow is never interrupted.

``script/review.py`` is a thin command-line adapter; the message pipeline calls
:meth:`PhotoReviewer.review` through ``MediaFileHandler`` and gates it with
:func:`probe_gateway` at startup.
"""

import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote

import httpx
from PIL import Image, ImageOps

MAX_IMAGE_EDGE = 1024
JPEG_QUALITY = 85
DATA_URI_PREFIX = "data:image/jpeg;base64,"
LOGGER_NAME = "file-bridge.review"
# Reviews are entertainment, so latency wins over reasoning depth: the gateway
# is asked not to think first. Measured on qwen3.5:9b-mlx this cuts output
# tokens roughly 4x (about 600-1200 -> 140) at the cost of looser adherence to
# the prompt's length budget.
REASONING_EFFORT = "none"

DEFAULT_REVIEW_PROMPT = (
    "你是资深摄影评论家。请用一段话点评这张照片：既分析美学与摄影技术（构图、光影、色彩、瞬间），"
    "也真诚夸赞照片、景色、模特与拍摄者。结合画面具体内容，不要分点、不要小标题、不要换行。"
    "最后请务必自查：全篇含标点不超过 100 字。"
)

ENV_BASE_URL = "OPENAI_BASE_URL"
ENV_API_KEY = "OPENAI_API_KEY"
ENV_MODEL = "OPENAI_MODEL"
REQUIRED_ENV = (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL)

API_KEY_MASK_LENGTH = 8
PROBE_TIMEOUT = 3.0


class ReviewConfigError(ValueError):
    """Raised when required gateway configuration is missing or blank."""

    def __init__(self, missing: List[str]):
        self.missing = tuple(missing)
        super().__init__(
            "missing required configuration: " + ", ".join(self.missing)
        )


@dataclass(frozen=True)
class ReviewConfig:
    """Gateway settings resolved from an explicit mapping, never from os.environ."""

    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ReviewConfig":
        """Build the config from *env*, raising ``ReviewConfigError`` on blanks.

        ``env`` is mandatory on purpose: callers pass ``os.environ`` at the
        entry point, and tests pass a literal dict, so no test ever needs to
        mutate the process environment.
        """
        missing = [
            name for name in REQUIRED_ENV if not str(env.get(name) or "").strip()
        ]
        if missing:
            raise ReviewConfigError(missing)
        return cls(
            base_url=str(env[ENV_BASE_URL]).strip().rstrip("/"),
            api_key=str(env[ENV_API_KEY]).strip(),
            model=str(env[ENV_MODEL]).strip(),
        )

    @classmethod
    def from_env_optional(cls, env: Mapping[str, str]) -> Optional["ReviewConfig"]:
        """Return a config when every required variable is present, else None.

        Message-chain callers treat a missing gateway configuration as "photo
        review disabled", while the CLI keeps using :meth:`from_env` and its
        fail-fast behaviour. Only ``ReviewConfigError`` is converted; any other
        exception still propagates.
        """
        try:
            return cls.from_env(env)
        except ReviewConfigError:
            return None


def _to_rgb(image: Image.Image) -> Image.Image:
    """Return an RGB image, compositing any alpha channel onto white."""
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _encode_image(path: str) -> str:
    """Encode the photo at *path* as a scaled-down JPEG data URI.

    The image is rotated by its EXIF orientation, scaled to fit a 1024x1024 box
    without cropping or upscaling, and kept entirely in memory. Raises on
    unreadable or unsupported input; :meth:`PhotoReviewer.review` degrades.
    """
    with Image.open(path) as source:
        source.seek(0)
        oriented = ImageOps.exif_transpose(source)
        rgb = _to_rgb(oriented)
        rgb.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return DATA_URI_PREFIX + base64.b64encode(buffer.getvalue()).decode("ascii")


def _mask_api_key(api_key: str) -> str:
    """Return a non-replayable fingerprint of an API key for diagnostics."""
    if not api_key:
        return "unavailable"
    if len(api_key) < API_KEY_MASK_LENGTH:
        return "***"
    return f"{api_key[:4]}...{api_key[-2:]}"


def models_endpoint(config: ReviewConfig) -> str:
    """Return the per-model probe URL with the model name URL-encoded.

    Model names may contain ``:`` (``qwen3.5:9b``); leaving it raw would let
    the gateway parse it as a path delimiter.
    """
    return f"{config.base_url}/models/{quote(config.model, safe='')}"


async def probe_gateway(
    config: ReviewConfig,
    timeout: float = PROBE_TIMEOUT,
    http_client: Optional[httpx.AsyncClient] = None,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """Check that the gateway answers for the configured model.

    Uses ``GET /models/{model}`` exactly like the deployment checklist: a 2xx
    proves the base URL, credentials and model name are consistent. It does
    NOT load the model, so the first review can still pay a cold-start cost.

    Never raises: every failure is logged as a warning and reported as False.
    """
    log = logger or logging.getLogger(LOGGER_NAME)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await client.get(
                models_endpoint(config),
                headers={"Authorization": f"Bearer {config.api_key}"},
            )
        except Exception as exc:
            log.warning(
                "Photo review unavailable (%s): %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            return False
    finally:
        if owns_client:
            await client.aclose()

    if response.is_success:
        log.info("Photo review ready: model=%s", config.model)
        return True

    log.warning(
        "Photo review unavailable (status=%s): %s",
        response.status_code,
        response.text[:200],
    )
    return False


class PhotoReviewer:
    """Requests an aesthetic review for a local photo from a vision gateway."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        http_client: Optional[httpx.AsyncClient] = None,
        logger: Optional[logging.Logger] = None,
        timeout: Optional[httpx.Timeout] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http_client = http_client
        self.logger = logger or logging.getLogger(LOGGER_NAME)
        # Only used when this instance creates its own client; an injected
        # client keeps whatever timeout its owner chose.
        self.timeout = timeout

    @property
    def endpoint(self) -> str:
        """Chat completions endpoint; the gateway base URL already has /v1."""
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, data_uri: str) -> Dict[str, Any]:
        return {
            "model": self.model,
            "reasoning_effort": REASONING_EFFORT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DEFAULT_REVIEW_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        }

    async def review(self, image_path: str) -> Optional[str]:
        """Return the review text, or ``None`` when no usable review is available.

        Never raises: decoding failures skip the request entirely, and gateway
        or parsing failures are logged and downgraded to ``None``.
        """
        try:
            # Pillow decoding is synchronous and may hit a cold disk; keep it
            # off the event loop so concurrent photo messages stay responsive.
            data_uri = await asyncio.to_thread(_encode_image, image_path)
        except Exception as exc:
            self.logger.debug(
                "Photo review skipped, image not decodable (%s): %s",
                type(exc).__name__,
                image_path,
            )
            return None

        if self.http_client is not None:
            return await self._request(self.http_client, data_uri)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._request(client, data_uri)

    async def _request(
        self, client: httpx.AsyncClient, data_uri: str
    ) -> Optional[str]:
        try:
            response = await client.post(
                self.endpoint, headers=self._headers(), json=self._payload(data_uri)
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            self.logger.warning(
                "Photo review gateway returned %s: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None
        except Exception as exc:
            self.logger.warning(
                "Photo review request failed (%s): %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            return None

        text = content.strip() if isinstance(content, str) else ""
        if not text:
            self.logger.warning(
                "Photo review gateway returned no usable content (model=%s, key=%s)",
                self.model,
                _mask_api_key(self.api_key),
            )
            return None
        return text
