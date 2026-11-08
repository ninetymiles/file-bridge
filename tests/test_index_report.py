"""Unit tests for index report rendering."""

import sqlite3
from unittest.mock import MagicMock

from app.services.index_report import EMPTY_REPORT_TEXT, format_index_report
from app.services.metadata_store import DailyStatistics, IndexStatistics


def _stats(
    total_files=0,
    total_users=0,
    typed_counts=None,
    null_saved_paths=(),
    daily=(),
):
    return IndexStatistics(
        total_files=total_files,
        total_users=total_users,
        typed_counts=typed_counts or {},
        null_saved_paths=tuple(null_saved_paths),
        daily=tuple(daily),
    )


def test_empty_index_report():
    assert format_index_report(_stats()) == EMPTY_REPORT_TEXT


def test_single_day_report_keeps_breakdown_without_totals():
    stats = _stats(
        total_files=3,
        total_users=2,
        typed_counts={"picture": 2, "video": 1},
        daily=[DailyStatistics("2026-11-08", 2, 3)],
    )

    text = format_index_report(stats)

    assert text == "索引统计：2026-11-08，用户 2 人，文件 3 份（照片 2，视频 1，其他 0）。"
    assert "索引总量" not in text


def test_multi_day_report_contains_totals_and_latest_day():
    stats = _stats(
        total_files=4,
        total_users=3,
        typed_counts={"picture": 2, "video": 1, "file": 1},
        daily=[
            DailyStatistics("2026-11-08", 2, 2),
            DailyStatistics("2026-11-07", 2, 2),
        ],
    )

    text = format_index_report(stats)

    assert text == (
        "索引总量：用户 3 人，文件 4 份（照片 2，视频 1，其他 1）。\n"
        "最近新增：2026-11-08，用户 2 人，文件 2 份。"
    )


def test_null_media_type_falls_back_to_extension():
    stats = _stats(
        total_files=4,
        total_users=2,
        typed_counts={"picture": 1},
        null_saved_paths=("x.png", "y.mov", "z.txt"),
        daily=[DailyStatistics("2026-11-08", 2, 4)],
    )

    text = format_index_report(stats)

    assert "照片 2，视频 1，其他 1" in text


def test_unknown_media_type_counts_as_other():
    stats = _stats(
        total_files=2,
        total_users=1,
        typed_counts={"picture": 1, "unexpected": 1},
        daily=[DailyStatistics("2026-11-08", 1, 2)],
    )

    text = format_index_report(stats)

    assert "照片 1，视频 0，其他 1" in text


def test_renderer_does_not_access_database(monkeypatch):
    monkeypatch.setattr(
        sqlite3, "connect", MagicMock(side_effect=AssertionError("renderer touched database"))
    )
    stats = _stats(
        total_files=1,
        total_users=1,
        typed_counts={"picture": 1},
        daily=[DailyStatistics("2026-11-08", 1, 1)],
    )

    assert "索引统计" in format_index_report(stats)
