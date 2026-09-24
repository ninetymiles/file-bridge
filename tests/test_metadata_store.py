"""Unit tests for MetadataStore."""

import os
import sqlite3
import pytest
from lib.metadata_store import MetadataStore


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

        # Verify index exists
        cursor.execute("PRAGMA index_list(file_metadata);")
        indices = [row[1] for row in cursor.fetchall()]
        assert "idx_file_sha256" in indices


def test_metadata_store_output_dir(tmp_path):
    out_dir = tmp_path / "my_output"
    store = MetadataStore(output_dir=str(out_dir))

    expected_db = out_dir / "metadata.sqlite"
    assert os.path.exists(expected_db)
    assert store.db_path == str(expected_db)


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
