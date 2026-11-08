"""Unit tests for index report rendering."""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock

from app.services.index_report import (
    EMPTY_REPORT_TEXT,
    format_daily_delta,
    format_index_snapshot,
)
from app.services.metadata_store import IndexStatistics


def _stats(
    total_files=0,
    total_users=0,
    typed_counts=None,
    null_saved_paths=(),
):
    return IndexStatistics(
        total_files=total_files,
        total_users=total_users,
        typed_counts=typed_counts or {},
        null_saved_paths=tuple(null_saved_paths),
        daily=(),
    )


def test_empty_snapshot():
    assert format_index_snapshot(_stats()) == EMPTY_REPORT_TEXT


def test_snapshot_single_line_totals():
    stats = _stats(
        total_files=3,
        total_users=2,
        typed_counts={"picture": 2, "video": 1},
    )

    text = format_index_snapshot(stats)

    assert text == "当前索引总量：2 位用户上传 3 份文件 (照片 2，视频 1，其他 0)"


def test_snapshot_with_all_types():
    stats = _stats(
        total_files=4,
        total_users=3,
        typed_counts={"picture": 2, "video": 1, "file": 1},
    )

    text = format_index_snapshot(stats)

    assert text == "当前索引总量：3 位用户上传 4 份文件 (照片 2，视频 1，其他 1)"


def test_snapshot_null_media_type_falls_back_to_extension():
    stats = _stats(
        total_files=4,
        total_users=2,
        typed_counts={"picture": 1},
        null_saved_paths=("x.png", "y.mov", "z.txt"),
    )

    text = format_index_snapshot(stats)

    assert "照片 2，视频 1，其他 1" in text


def test_snapshot_unknown_media_type_counts_as_other():
    stats = _stats(
        total_files=2,
        total_users=1,
        typed_counts={"picture": 1, "unexpected": 1},
    )

    text = format_index_snapshot(stats)

    assert "照片 1，视频 0，其他 1" in text


def test_snapshot_does_not_access_database(monkeypatch):
    monkeypatch.setattr(
        sqlite3, "connect", MagicMock(side_effect=AssertionError("renderer touched database"))
    )
    stats = _stats(total_files=1, total_users=1, typed_counts={"picture": 1})

    assert "当前索引总量" in format_index_snapshot(stats)


def test_daily_delta_format():
    stats = _stats(
        total_files=5,
        total_users=2,
        typed_counts={"picture": 3, "video": 1, "file": 1},
    )
    last_check = datetime(2026, 11, 7, 9, 0, 0)

    text = format_daily_delta(stats, last_check)

    assert text == "自2026-11-07 09:00 新增：2 位用户上传 5 份文件 (照片 3，视频 1，其他 1)"


def test_daily_delta_null_media_type_falls_back():
    stats = _stats(
        total_files=2,
        total_users=1,
        typed_counts={"picture": 1},
        null_saved_paths=("clip.mp4",),
    )
    last_check = datetime(2026, 11, 7, 9, 0, 0)

    text = format_daily_delta(stats, last_check)

    assert "照片 1，视频 1，其他 0" in text
