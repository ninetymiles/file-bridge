"""Unit tests for app.services.media_metadata."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.services.media_metadata import (
    extract_media_metadata,
    extract_photo_metadata,
    extract_video_metadata,
    format_photo_line,
    format_video_line,
    PhotoMetadata,
    VideoMetadata,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NIKON_FIXTURE = FIXTURES_DIR / "sample_nikon_z63.JPG"
HONOR_ORIGINAL_FIXTURE = FIXTURES_DIR / "sample_honor_ptp_an00_original.png"
HONOR_THUMBNAIL_FIXTURE = FIXTURES_DIR / "sample_honor_ptp_an00_thumbnail.png"


def _make_jpeg_with_subifd(path, sub_ifd_fields: dict, ifd0_fields: dict | None = None):
    """Create a JPEG with tags in the Exif sub-IFD, mirroring real cameras.

    Real cameras write shooting parameters under the Exif sub-IFD (0x8769),
    never directly into IFD0. The earlier IFD0-based fixtures were invalid
    and masked the sub-IFD lookup bug.
    """
    img = Image.new("RGB", (64, 64), color=(255, 0, 0))
    exif = img.getexif()
    for tag_id, value in (ifd0_fields or {}).items():
        exif[tag_id] = value
    sub_ifd = exif.get_ifd(0x8769)
    for tag_id, value in sub_ifd_fields.items():
        sub_ifd[tag_id] = value
    img.save(str(path), exif=exif.tobytes())


# ---------- Photo metadata: real camera fixtures ----------

def test_nikon_fixture_full_fields():
    """Standard EXIF 2.3 camera: all four fields, ISO in 0x8827."""
    meta = extract_photo_metadata(str(NIKON_FIXTURE))

    assert meta is not None
    assert meta.datetime_original == "2026:09:12 14:58:16"
    assert meta.f_number == pytest.approx(5.6)
    assert meta.exposure_time == pytest.approx(1 / 320)
    assert meta.iso == 200
    assert extract_media_metadata(str(NIKON_FIXTURE), "picture") == (
        "2026-09-12 14:58:16  f/5.6  1/320s  ISO 200"
    )


def test_honor_original_fixture_iso_8833_without_time():
    """EXIF 2.31 camera: ISO only in 0x8833, no capture-time tags at all."""
    meta = extract_photo_metadata(str(HONOR_ORIGINAL_FIXTURE))

    assert meta is not None
    assert meta.datetime_original is None
    assert meta.f_number == pytest.approx(1.9)
    assert meta.exposure_time == pytest.approx(1 / 33, abs=1e-3)
    assert meta.iso == 320
    assert extract_media_metadata(str(HONOR_ORIGINAL_FIXTURE), "picture") == (
        "f/1.9  1/33s  ISO 320"
    )


def test_honor_thumbnail_fixture_stripped_exif():
    """Transport-processed thumbnail: EXIF shooting tags fully removed."""
    assert extract_photo_metadata(str(HONOR_THUMBNAIL_FIXTURE)) is None
    assert extract_media_metadata(str(HONOR_THUMBNAIL_FIXTURE), "picture") is None


# ---------- Photo metadata: programmatic sub-IFD fixtures ----------

def test_extract_photo_full_exif_sub_ifd(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(
        path,
        {
            0x9003: "2024:01:15 14:30:00",
            0x829D: (28, 10),
            0x829A: (1, 500),
            0x8827: 400,
        },
    )

    meta = extract_photo_metadata(str(path))

    assert meta is not None
    assert meta.datetime_original == "2024:01:15 14:30:00"
    assert meta.f_number == 2.8
    assert meta.exposure_time == 0.002
    assert meta.iso == 400


def test_extract_photo_partial_exif(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(path, {0x9003: "2024:01:15 14:30:00", 0x8827: 100})

    meta = extract_photo_metadata(str(path))

    assert meta is not None
    assert meta.datetime_original == "2024:01:15 14:30:00"
    assert meta.iso == 100
    assert meta.f_number is None
    assert meta.exposure_time is None


def test_extract_iso_fallback_to_8833(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(path, {0x8830: 3, 0x8833: 640})

    meta = extract_photo_metadata(str(path))

    assert meta is not None
    assert meta.iso == 640


def test_extract_iso_fallback_to_8832(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(path, {0x8832: 160})

    meta = extract_photo_metadata(str(path))

    assert meta is not None
    assert meta.iso == 160


def test_extract_iso_prefers_8827_over_new_tags(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(path, {0x8827: 200, 0x8833: 640, 0x8832: 800})

    meta = extract_photo_metadata(str(path))

    assert meta is not None
    assert meta.iso == 200


def test_extract_datetime_nul_terminated(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(path, {0x9003: "2024:01:15 14:30:00\x00", 0x8827: 100})

    meta = extract_photo_metadata(str(path))

    assert meta is not None
    assert meta.datetime_original == "2024:01:15 14:30:00"


def test_tags_in_ifd0_only_are_not_misread(tmp_path):
    """Regression: IFD0 carries Make/Model but shooting tags live in sub-IFD.

    A file whose sub-IFD lacks every target field must return None even when
    IFD0 has plenty of other EXIF content (the original bug read IFD0).
    """
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(
        path,
        sub_ifd_fields={},
        ifd0_fields={0x010F: "HONOR", 0x0110: "PTP-AN00", 0x0112: 1},
    )

    assert extract_photo_metadata(str(path)) is None


def test_extract_photo_no_exif(tmp_path):
    path = tmp_path / "plain.png"
    Image.new("RGB", (32, 32)).save(str(path))

    assert extract_photo_metadata(str(path)) is None


def test_extract_photo_missing_file():
    assert extract_photo_metadata("/nonexistent/photo.jpg") is None


# ---------- Photo formatting ----------

def test_format_photo_line_all_fields():
    meta = PhotoMetadata(
        datetime_original="2024:01:15 14:30:00",
        f_number=2.8,
        exposure_time=0.002,
        iso=400,
    )
    assert format_photo_line(meta) == "2024-01-15 14:30:00  f/2.8  1/500s  ISO 400"


def test_format_photo_line_only_time_and_iso():
    meta = PhotoMetadata(datetime_original="2024:01:15 14:30:00", iso=100)
    assert format_photo_line(meta) == "2024-01-15 14:30:00  ISO 100"


def test_format_photo_exposure_long_shutter():
    # >= 1 second should render as "<N>s", not "1/Ns".
    meta = PhotoMetadata(exposure_time=2.0)
    assert "2s" in format_photo_line(meta)


# ---------- Video metadata ----------

def _fake_video_track(width=544, height=960, frame_rate="30.204"):
    track = MagicMock()
    track.width = width
    track.height = height
    track.frame_rate = frame_rate
    return track


def _fake_media_info(track):
    mi = MagicMock()
    mi.video_tracks = [track]
    return mi


def test_extract_video_success(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"not a real video")  # content irrelevant; parse is mocked

    with patch("pymediainfo.MediaInfo.parse") as mock_parse:
        mock_parse.return_value = _fake_media_info(_fake_video_track())
        meta = extract_video_metadata(str(path))

    assert meta is not None
    assert meta.width == 544
    assert meta.height == 960
    assert meta.frame_rate == pytest.approx(30.204)


def test_extract_video_no_video_track(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"x")

    with patch("pymediainfo.MediaInfo.parse") as mock_parse:
        mi = MagicMock()
        mi.video_tracks = []
        mock_parse.return_value = mi
        assert extract_video_metadata(str(path)) is None


def test_extract_video_parse_exception(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"x")

    with patch("pymediainfo.MediaInfo.parse", side_effect=RuntimeError("boom")):
        assert extract_video_metadata(str(path)) is None


def test_format_video_line():
    meta = VideoMetadata(width=1920, height=1080, frame_rate=29.97)
    assert format_video_line(meta) == "1920x1080  30.0fps"


def test_format_video_line_no_frame_rate():
    meta = VideoMetadata(width=544, height=960, frame_rate=None)
    assert format_video_line(meta) == "544x960"


# ---------- Entry point dispatch ----------

def test_extract_media_metadata_picture(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_subifd(path, {0x9003: "2024:01:15 14:30:00", 0x8827: 400})
    assert extract_media_metadata(str(path), "picture") == "2024-01-15 14:30:00  ISO 400"


def test_extract_media_metadata_video(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"x")
    with patch("pymediainfo.MediaInfo.parse") as mock_parse:
        mock_parse.return_value = _fake_media_info(_fake_video_track())
        assert extract_media_metadata(str(path), "video") == "544x960  30.2fps"


def test_extract_media_metadata_file_returns_none(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"pdf")
    assert extract_media_metadata(str(path), "file") is None


def test_extract_media_metadata_picture_no_exif_returns_none(tmp_path):
    path = tmp_path / "plain.png"
    Image.new("RGB", (16, 16)).save(str(path))
    assert extract_media_metadata(str(path), "picture") is None
