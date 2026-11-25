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
WARMUP_CONNECT_TIMEOUT = 5.0
WARMUP_READ_TIMEOUT = 30.0
WARMUP_TIMEOUT = httpx.Timeout(
    WARMUP_CONNECT_TIMEOUT, read=WARMUP_READ_TIMEOUT
)
WARMUP_MAX_TOKENS = 1
WARMUP_PROMPT = "ping"
AVAILABLE_MODEL_SAMPLE = 5


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


@dataclass(frozen=True)
class GatewayProbe:
    """Result of the startup gateway health check.

    ``ready`` is the only capability gate: the gateway answered successfully
    and the configured model appears in its model list.
    """

    reachable: bool
    status: Optional[int]
    models: tuple[str, ...]
    model_present: bool
    error: Optional[str] = None

    @property
    def ready(self) -> bool:
        """Return True only when the API is reachable and the model is listed."""
        return self.reachable and self.model_present


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
    """Return the model-list endpoint used by the startup health check."""
    return f"{config.base_url}/models"


def _parse_model_ids(payload: Any) -> Optional[tuple[str, ...]]:
    """Extract model ids from an OpenAI-compatible ``/models`` payload.

    Only the base OpenAI shape is supported: ``{"data": [{"id": "..."}]}``.
    Entries that are not objects, or whose ``id`` is not a non-empty string,
    are skipped. Returns ``None`` when the payload carries no ``data`` list,
    so the caller can treat model availability as unverified.
    """
    if not isinstance(payload, dict):
        return None
    entries = payload.get("data")
    if not isinstance(entries, list):
        return None

    model_ids = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if isinstance(model_id, str) and model_id.strip():
            model_ids.append(model_id)
    return tuple(model_ids)


def _format_available(models: tuple[str, ...]) -> str:
    """Render a short, truncated sample of available model ids."""
    sample = models[:AVAILABLE_MODEL_SAMPLE]
    rendered = ", ".join(sample)
    if len(models) > len(sample):
        rendered = f"{rendered}, ..."
    return f"[{rendered}]"


async def probe_gateway(
    config: ReviewConfig,
    timeout: float = PROBE_TIMEOUT,
    http_client: Optional[httpx.AsyncClient] = None,
    logger: Optional[logging.Logger] = None,
) -> GatewayProbe:
    """Check that the gateway is reachable and exposes the configured model.

    Uses ``GET /models`` and checks the configured model name against the
    returned list. A 2xx alone only proves the route and credentials; the
    configured model must also be present before photo review is enabled.

    Never raises: every failure is reported in a single log line and returned
    as a non-ready :class:`GatewayProbe`.
    """
    log = logger or logging.getLogger(LOGGER_NAME)
    url = models_endpoint(config)
    key = _mask_api_key(config.api_key)
    log.debug("Photo review probe: GET %s model=%s", url, config.model)

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {config.api_key}"},
            )
        except Exception as exc:
            log.warning(
                "Photo review health FAILED: url=%s model=%s error=%s:%s key=%s",
                url,
                config.model,
                type(exc).__name__,
                str(exc)[:200],
                key,
            )
            return GatewayProbe(
                reachable=False,
                status=None,
                models=(),
                model_present=False,
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
    finally:
        if owns_client:
            await client.aclose()

    if not response.is_success:
        log.warning(
            "Photo review health FAILED: url=%s model=%s status=%s body=%s key=%s",
            url,
            config.model,
            response.status_code,
            response.text[:200],
            key,
        )
        return GatewayProbe(
            reachable=False,
            status=response.status_code,
            models=(),
            model_present=False,
            error=f"HTTP {response.status_code}",
        )

    try:
        payload = response.json()
    except Exception as exc:
        log.warning(
            "Photo review health FAILED: url=%s model=%s error=%s:%s key=%s",
            url,
            config.model,
            type(exc).__name__,
            str(exc)[:200],
            key,
        )
        return GatewayProbe(
            reachable=True,
            status=response.status_code,
            models=(),
            model_present=False,
            error=f"invalid model list JSON: {type(exc).__name__}",
        )

    models = _parse_model_ids(payload)
    if models is None:
        log.warning(
            "Photo review health FAILED: url=%s model=%s error=unparsable_model_list key=%s",
            url,
            config.model,
            key,
        )
        return GatewayProbe(
            reachable=True,
            status=response.status_code,
            models=(),
            model_present=False,
            error="unparsable model list",
        )

    log.debug("Photo review models: %s", list(models))
    model_present = config.model in models
    if model_present:
        log.info(
            "Photo review health OK: url=%s model=%s models=%d present=yes key=%s",
            url,
            config.model,
            len(models),
            key,
        )
        return GatewayProbe(
            reachable=True,
            status=response.status_code,
            models=models,
            model_present=True,
        )

    log.warning(
        "Photo review health FAILED: url=%s model=%s models=%d present=no available=%s key=%s",
        url,
        config.model,
        len(models),
        _format_available(models),
        key,
    )
    return GatewayProbe(
        reachable=True,
        status=response.status_code,
        models=models,
        model_present=False,
        error="model not listed",
    )


_warmup_in_flight = False


async def warmup_model(
    config: ReviewConfig,
    http_client: Optional[httpx.AsyncClient] = None,
    logger: Optional[logging.Logger] = None,
    timeout: httpx.Timeout = WARMUP_TIMEOUT,
) -> None:
    """Send a minimal chat request so the gateway starts loading the model.

    Called only when a cold-disk wakeup is under way. One in-flight request is
    enough: concurrent cold messages return early instead of stacking traffic.
    Never raises and never changes the review enable decision; a failure is
    reported as a single WARNING line.
    """
    global _warmup_in_flight
    if _warmup_in_flight:
        return
    _warmup_in_flight = True

    log = logger or logging.getLogger(LOGGER_NAME)
    url = f"{config.base_url}/chat/completions"
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": WARMUP_PROMPT}],
        "max_tokens": WARMUP_MAX_TOKENS,
        "reasoning_effort": REASONING_EFFORT,
    }
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except Exception as exc:
            log.warning(
                "Photo review warmup FAILED: url=%s model=%s error=%s:%s",
                url,
                config.model,
                type(exc).__name__,
                str(exc)[:200],
            )
            return

        if response.is_success:
            log.debug(
                "Photo review warmup OK: url=%s model=%s key=%s",
                url,
                config.model,
                _mask_api_key(config.api_key),
            )
            return
        log.warning(
            "Photo review warmup FAILED: url=%s model=%s status=%s body=%s key=%s",
            url,
            config.model,
            response.status_code,
            response.text[:200],
            _mask_api_key(config.api_key),
        )
    finally:
        _warmup_in_flight = False
        if owns_client:
            await client.aclose()


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
