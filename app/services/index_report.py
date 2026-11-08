"""Render index statistics as chat report text."""

import os

from app.services.metadata_store import IndexStatistics

PHOTO_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif", ".tif", ".tiff"}
)
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"})

EMPTY_REPORT_TEXT = "索引中暂无文件记录。"


def _classify_null_path(saved_path: str) -> str:
    extension = os.path.splitext(saved_path)[1].lower()
    if extension in PHOTO_EXTENSIONS:
        return "picture"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def _type_counts(stats: IndexStatistics) -> tuple[int, int, int]:
    photo_count = stats.typed_counts.get("picture", 0)
    video_count = stats.typed_counts.get("video", 0)

    # Old-version writers leave media_type NULL; classify those rows by
    # extension so they still contribute to the type breakdown.
    for saved_path in stats.null_saved_paths:
        kind = _classify_null_path(saved_path)
        if kind == "picture":
            photo_count += 1
        elif kind == "video":
            video_count += 1

    other_count = stats.total_files - photo_count - video_count
    return photo_count, video_count, other_count


def format_index_report(stats: IndexStatistics) -> str:
    """Format the statistics report, collapsing totals when only one day exists."""
    if not stats.daily:
        return EMPTY_REPORT_TEXT

    photo_count, video_count, other_count = _type_counts(stats)
    breakdown = f"照片 {photo_count}，视频 {video_count}，其他 {other_count}"
    latest = stats.daily[0]

    if len(stats.daily) == 1:
        return (
            f"索引统计：{latest.day}，用户 {latest.users} 人，文件 {latest.files} 份"
            f"（{breakdown}）。"
        )

    return (
        f"索引总量：用户 {stats.total_users} 人，文件 {stats.total_files} 份"
        f"（{breakdown}）。\n"
        f"最近新增：{latest.day}，用户 {latest.users} 人，文件 {latest.files} 份。"
    )
