"""Unit tests for MetadataStore."""

import os
import sqlite3
import pytest
from app.services.metadata_store import (
    CURRENT_SCHEMA_VERSION,
    DailyStatistics,
    MetadataStore,
    UnsupportedSchemaVersion,
)


def test_metadata_store_init(tmp_path):
    db_file = tmp_path / "subdir" / "metadata.sqlite"
    store = MetadataStore(db_path=str(db_file))

    assert os.path.exists(db_file)

    with sqlite3.connect(str(db_file)) as conn:
        cursor = conn.cursor()
        # Verify file_metadata table columns
        cursor.execute("PRAGMA table_info(file_metadata);")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert "id" in columns
        assert "sender_id" in columns
        assert "sender_nick" in columns
        assert "created_at" in columns
        assert "original_filename" in columns
        assert "saved_path" in columns
        assert "sha256" in columns
        assert "file_size" in columns
        assert "media_type" in columns

        # Verify index exists
        cursor.execute("PRAGMA index_list(file_metadata);")
        indices = [row[1] for row in cursor.fetchall()]
        assert "idx_file_sha256" in indices

        # Verify the schema version is stamped on creation
        cursor.execute("PRAGMA user_version;")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_metadata_store_output_dir(tmp_path):
    out_dir = tmp_path / "my_output"
    store = MetadataStore(output_dir=str(out_dir))

    expected_db = out_dir / "metadata.sqlite"
    assert os.path.exists(expected_db)
    assert store.db_path == str(expected_db)


def test_existing_database_without_version_is_refused(tmp_path):
    db_file = tmp_path / "metadata.sqlite"
    db_file.touch()

    with pytest.raises(UnsupportedSchemaVersion):
        MetadataStore(db_path=str(db_file))

    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("PRAGMA user_version;").fetchone()[0] == 0
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_metadata'"
        ).fetchone()
        assert tables is None


def test_higher_database_version_is_refused(tmp_path):
    db_file = tmp_path / "metadata.sqlite"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA user_version = 2;")
        conn.commit()

    with pytest.raises(UnsupportedSchemaVersion):
        MetadataStore(db_path=str(db_file))

    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("PRAGMA user_version;").fetchone()[0] == 2


def test_get_index_statistics(tmp_path):
    store = MetadataStore(db_path=str(tmp_path / "metadata.sqlite"))

    store.insert_record(
        "u1", "a.jpg", str(tmp_path / "a.jpg"), "s1", 10,
        created_at="2026-11-07 10:00:00", media_type="picture",
    )
    store.insert_record(
        "u2", "b.mp4", str(tmp_path / "b.mp4"), "s2", 20,
        created_at="2026-11-07 11:00:00", media_type="video",
    )
    store.insert_record(
        "u1", "c.pdf", str(tmp_path / "c.pdf"), "s3", 30,
        created_at="2026-11-08 09:00:00", media_type="file",
    )
    store.insert_record(
        "u3", "d.png", str(tmp_path / "d.png"), "s4", 40,
        created_at="2026-11-08 10:00:00",
    )

    stats = store.get_index_statistics()

    assert stats.total_files == 4
    assert stats.total_users == 3
    assert stats.typed_counts == {"picture": 1, "video": 1, "file": 1}
    assert stats.null_saved_paths == (str(tmp_path / "d.png"),)
    assert stats.daily == (
        DailyStatistics("2026-11-08", 2, 2),
        DailyStatistics("2026-11-07", 2, 2),
    )


def test_existing_versioned_database_reopens(tmp_path):
    db_file = tmp_path / "metadata.sqlite"
    first = MetadataStore(db_path=str(db_file))
    first.insert_record("u1", "a.jpg", str(tmp_path / "a.jpg"), "s1", 1, media_type="picture")

    reopened = MetadataStore(db_path=str(db_file))
    stats = reopened.get_index_statistics()

    assert stats.total_files == 1
    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("PRAGMA user_version;").fetchone()[0] == CURRENT_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_async_statistics_match_sync(tmp_path):
    store = MetadataStore(db_path=str(tmp_path / "metadata.sqlite"))
    store.insert_record(
        "u1", "a.jpg", str(tmp_path / "a.jpg"), "s1", 1,
        created_at="2026-11-08 10:00:00", media_type="picture",
    )

    sync_stats = store.get_index_statistics()
    async_stats = await store.async_get_index_statistics()

    assert async_stats == sync_stats


def test_empty_index_statistics(tmp_path):
    store = MetadataStore(db_path=str(tmp_path / "metadata.sqlite"))

    stats = store.get_index_statistics()

    assert stats.total_files == 0
    assert stats.total_users == 0
    assert stats.typed_counts == {}
    assert stats.null_saved_paths == ()
    assert stats.daily == ()


@pytest.mark.asyncio
async def test_duplicate_detection(tmp_path):
    db_file = tmp_path / "metadata.sqlite"
    store = MetadataStore(db_path=str(db_file))

    dummy_file = tmp_path / "file1.txt"
    dummy_file.write_text("hello world")
    dummy_sha256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    # Not in DB yet
    assert not store.is_duplicate(dummy_sha256)
    assert not await store.async_is_duplicate(dummy_sha256)

    # Insert into DB and file exists
    store.insert_record(
        sender_id="user1",
        original_filename="file1.txt",
        saved_path=str(dummy_file),
        sha256=dummy_sha256,
        file_size=11,
    )

    assert store.is_duplicate(dummy_sha256)
    assert await store.async_is_duplicate(dummy_sha256)

    # File on disk removed (e.g. archived)
    dummy_file.unlink()
    assert not store.is_duplicate(dummy_sha256)
    assert not await store.async_is_duplicate(dummy_sha256)


@pytest.mark.asyncio
async def test_rebuild_index(tmp_path):
    db_file = tmp_path / "metadata.sqlite"
    store = MetadataStore(db_path=str(db_file))

    # Create 3 files on disk
    f1 = tmp_path / "f1.txt"
    f1.write_text("file 1")
    f2 = tmp_path / "f2.txt"
    f2.write_text("file 2")
    f3 = tmp_path / "f3.txt"
    f3.write_text("file 3")

    store.insert_record("u1", "f1.txt", str(f1), "sha1", 6, "User 1")
    store.insert_record("u2", "f2.txt", str(f2), "sha2", 6, "User 2")
    store.insert_record("u3", "f3.txt", str(f3), "sha3", 6, "User 3")

    # Before removing: rebuild should clean 0
    cleaned, remaining = await store.async_rebuild_index()
    assert cleaned == 0
    assert remaining == 3

    # Delete f1 and f3 on disk
    f1.unlink()
    f3.unlink()

    # Rebuild index should clean 2 and leave 1
    cleaned, remaining = await store.async_rebuild_index()
    assert cleaned == 2
    assert remaining == 1

    # Verify database contents
    with store.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT original_filename FROM file_metadata")
        records = [row["original_filename"] for row in cursor.fetchall()]
        assert records == ["f2.txt"]
