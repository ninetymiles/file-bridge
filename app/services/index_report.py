"""Render index statistics as chat report text."""

import os
from datetime import datetime

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


def format_index_snapshot(stats: IndexStatistics) -> str:
    """Format a single-line total snapshot of the current index.

    Used by the manual report command, the startup snapshot, and the
    total line of the daily delta report. Returns :data:`EMPTY_REPORT_TEXT`
    when the index has no records.
    """
    if stats.total_files == 0:
        return EMPTY_REPORT_TEXT

    photo_count, video_count, other_count = _type_counts(stats)
    return (
        f"当前索引总量：{stats.total_users} 位用户上传 {stats.total_files} 份文件 "
        f"(照片 {photo_count}，视频 {video_count}，其他 {other_count})"
    )


def format_daily_delta(delta_stats: IndexStatistics, last_check: datetime) -> str:
    """Format the daily incremental report line.

    ``delta_stats`` is the aggregation of records created after
    ``last_check``; ``last_check`` is rendered to minute precision.
    """
    photo_count, video_count, other_count = _type_counts(delta_stats)
    since = last_check.strftime("%Y-%m-%d %H:%M")
    return (
        f"自{since} 新增：{delta_stats.total_users} 位用户上传 "
        f"{delta_stats.total_files} 份文件 "
        f"(照片 {photo_count}，视频 {video_count}，其他 {other_count})"
    )


# Backward-compatible alias retained for callers that still import the old
# name; the manual command handler is updated to use format_index_snapshot.
format_index_report = format_index_snapshot
