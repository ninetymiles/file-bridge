"""Extract basic metadata from saved image/video files for reply display.

Photos are parsed with Pillow's EXIF reader (Layer-1 fields only: capture
time, aperture, shutter speed, ISO). Videos are parsed with pymediainfo
(resolution, frame rate). Any extraction failure returns None so the
save-and-reply flow is never interrupted.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("file-bridge.media")

# EXIF tag IDs.
_EXIF_IFD_POINTER = 0x8769  # IFD0 pointer to the Exif sub-IFD
_EXIF_DATETIME_ORIGINAL = 0x9003
_EXIF_FNUMBER = 0x829D
_EXIF_EXPOSURE_TIME = 0x829A
_EXIF_ISO_SPEED_RATINGS = 0x8827       # EXIF 2.3
_EXIF_ISO_SPEED = 0x8833               # EXIF 2.31 (SensitivityType=3)
_EXIF_RECOMMENDED_EXPOSURE_INDEX = 0x8832


@dataclass
class PhotoMetadata:
    """Layer-1 EXIF fields extracted from a photo."""

    datetime_original: Optional[str] = None
    f_number: Optional[float] = None
    exposure_time: Optional[float] = None
    iso: Optional[int] = None


@dataclass
class VideoMetadata:
    """Container metadata extracted from a video."""

    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[float] = None


def _format_datetime(value: str) -> str:
    """Convert EXIF DateTimeOriginal 'YYYY:MM:DD HH:MM:SS' to 'YYYY-MM-DD HH:MM:SS'.

    Some cameras NUL-terminate the value; strip trailing NULs and whitespace
    before parsing.
    """
    cleaned = value.strip().rstrip("\x00").strip()
    # Only the date portion uses colons as separators; time uses colons too,
    # so replace the first two colons (date separators) with hyphens.
    parts = cleaned.split(":", 2)
    if len(parts) == 3:
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return cleaned


def _format_fnumber(value: float) -> str:
    """Format aperture as 'f/2.8'."""
    if value == int(value):
        return f"f/{int(value)}"
    return f"f/{value:g}"


def _format_exposure(value: float) -> str:
    """Format shutter speed: <1s -> '1/Ns', >=1s -> 'Ns'."""
    if value >= 1.0:
        if value == int(value):
            return f"{int(value)}s"
        return f"{value:g}s"
    # Express as 1/N where possible.
    denominator = round(1.0 / value)
    if denominator > 0 and abs(1.0 / denominator - value) < 1e-6:
        return f"1/{denominator}s"
    return f"{value:g}s"


def _format_iso(value: int) -> str:
    """Format ISO as 'ISO 400'."""
    return f"ISO {value}"


def _format_resolution(width: int, height: int) -> str:
    """Format resolution as '1920x1080'."""
    return f"{width}x{height}"


def _format_frame_rate(value: float) -> str:
    """Format frame rate as '29.8fps' (one decimal place)."""
    return f"{value:.1f}fps"


def _to_float(value) -> Optional[float]:
    """Convert an EXIF rational/float/str value to float, or None on failure.

    Real photos expose rationals as Pillow IFDRational (supports float());
    test fixtures and some sources yield plain (numerator, denominator)
    tuples, so both forms are accepted.
    """
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        try:
            return float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    """Convert a value to int, or None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_exif_text(value) -> Optional[str]:
    """Strip trailing whitespace/NULs from an EXIF string; None when empty."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip("\x00").strip()
    return cleaned or None


def _extract_iso(tags) -> Optional[int]:
    """Resolve ISO across EXIF versions: 0x8827 -> 0x8833 -> 0x8832."""
    for tag_id in (_EXIF_ISO_SPEED_RATINGS, _EXIF_ISO_SPEED, _EXIF_RECOMMENDED_EXPOSURE_INDEX):
        iso = _to_int(tags.get(tag_id))
        if iso is not None and iso > 0:
            return iso
    return None


def extract_photo_metadata(path: str) -> Optional[PhotoMetadata]:
    """Extract Layer-1 EXIF fields from a photo file.

    Camera shooting parameters live in the Exif sub-IFD (pointed to by IFD0
    tag 0x8769), not in IFD0 itself. Returns None when no usable fields are
    present (stripped thumbnail, screenshot) or parsing fails.
    """
    try:
        from PIL import Image

        with Image.open(path) as img:
            ifd0 = img.getexif()
            # Resolve the nested IFD while the file is still open.
            sub_ifd = ifd0.get_ifd(_EXIF_IFD_POINTER) if _EXIF_IFD_POINTER in ifd0 else {}
    except Exception as exc:
        logger.debug("Photo EXIF parse failed for %s: %s", path, exc)
        return None

    if not ifd0 and not sub_ifd:
        logger.debug("Photo has no EXIF segment: %s", path)
        return None

    meta = PhotoMetadata(
        datetime_original=_clean_exif_text(sub_ifd.get(_EXIF_DATETIME_ORIGINAL)),
        f_number=_to_float(sub_ifd.get(_EXIF_FNUMBER)),
        exposure_time=_to_float(sub_ifd.get(_EXIF_EXPOSURE_TIME)),
        iso=_extract_iso(sub_ifd),
    )

    if not any(
        [meta.datetime_original, meta.f_number, meta.exposure_time, meta.iso]
    ):
        logger.debug("Photo EXIF has no usable shooting fields: %s", path)
        return None

    return meta


def extract_video_metadata(path: str) -> Optional[VideoMetadata]:
    """Extract resolution and frame rate from a video via pymediainfo.

    Returns None if parsing fails or the video track is missing.
    """
    try:
        from pymediainfo import MediaInfo

        media_info = MediaInfo.parse(path)
    except Exception as exc:
        logger.debug("Video metadata parse failed for %s: %s", path, exc)
        return None

    video_tracks = getattr(media_info, "video_tracks", None) or []
    if not video_tracks:
        logger.debug("Video has no video track: %s", path)
        return None

    track = video_tracks[0]
    width = _to_int(getattr(track, "width", None))
    height = _to_int(getattr(track, "height", None))
    frame_rate = _to_float(getattr(track, "frame_rate", None))

    if width is None or height is None:
        logger.debug("Video track missing dimensions: %s", path)
        return None

    return VideoMetadata(width=width, height=height, frame_rate=frame_rate)


def format_photo_line(meta: PhotoMetadata) -> str:
    """Build a single-line summary of available photo metadata fields."""
    parts = []
    if meta.datetime_original:
        parts.append(_format_datetime(meta.datetime_original))
    if meta.f_number is not None:
        parts.append(_format_fnumber(meta.f_number))
    if meta.exposure_time is not None:
        parts.append(_format_exposure(meta.exposure_time))
    if meta.iso is not None:
        parts.append(_format_iso(meta.iso))
    return "  ".join(parts)


def format_video_line(meta: VideoMetadata) -> str:
    """Build a single-line summary of available video metadata fields."""
    parts = []
    if meta.width is not None and meta.height is not None:
        parts.append(_format_resolution(meta.width, meta.height))
    if meta.frame_rate is not None:
        parts.append(_format_frame_rate(meta.frame_rate))
    return "  ".join(parts)


def extract_media_metadata(path: str, msgtype: str) -> Optional[str]:
    """Dispatch metadata extraction by message type.

    Returns the formatted metadata summary line, or None when no metadata
    is available (missing fields, parse failure, or unsupported type).
    """
    if msgtype == "picture":
        meta = extract_photo_metadata(path)
        if meta is None:
            return None
        line = format_photo_line(meta)
        if line:
            logger.debug("Photo metadata: %s (%s)", line, path)
            return line
        return None
    if msgtype == "video":
        meta = extract_video_metadata(path)
        if meta is None:
            return None
        line = format_video_line(meta)
        if line:
            logger.debug("Video metadata: %s (%s)", line, path)
            return line
        return None
    return None
