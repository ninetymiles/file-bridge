"""SQLite metadata store for tracking received files and deduplication."""

import asyncio
import os
import sqlite3
from typing import Optional, Tuple, List, Dict, Any


class MetadataStore:
    """Manages file metadata and deduplication index in SQLite."""

    def __init__(self, db_path: Optional[str] = None, output_dir: Optional[str] = None):
        if db_path:
            self.db_path = os.path.abspath(db_path)
        elif output_dir:
            self.db_path = os.path.abspath(os.path.join(output_dir, "metadata.sqlite"))
        else:
            self.db_path = os.path.abspath("./output/metadata.sqlite")

        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create a connection with row factory configured."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize database directory, tables, and indices."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id TEXT NOT NULL,
                    sender_nick TEXT,
                    created_at TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    saved_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_size INTEGER
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_sha256 ON file_metadata(sha256);")
            conn.commit()

    async def async_init_db(self) -> None:
        """Asynchronously initialize the database."""
        await asyncio.to_thread(self.init_db)

    def insert_record(
        self,
        sender_id: str,
        original_filename: str,
        saved_path: str,
        sha256: str,
        file_size: Optional[int] = None,
        sender_nick: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> int:
        """Insert a file metadata record into SQLite."""
        if created_at is None:
            from datetime import datetime
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO file_metadata (
                    sender_id, sender_nick, created_at, original_filename, saved_path, sha256, file_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sender_id, sender_nick, created_at, original_filename, saved_path, sha256, file_size),
            )
            conn.commit()
            return cursor.lastrowid

    async def async_insert_record(
        self,
        sender_id: str,
        original_filename: str,
        saved_path: str,
        sha256: str,
        file_size: Optional[int] = None,
        sender_nick: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> int:
        """Asynchronously insert a file metadata record into SQLite."""
        return await asyncio.to_thread(
            self.insert_record,
            sender_id,
            original_filename,
            saved_path,
            sha256,
            file_size,
            sender_nick,
            created_at,
        )

    def is_duplicate(self, sha256: str) -> bool:
        """Check if file with given sha256 exists in database AND actually exists on disk."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT saved_path FROM file_metadata WHERE sha256 = ?", (sha256,))
            rows = cursor.fetchall()
            for row in rows:
                saved_path = row["saved_path"]
                if os.path.exists(saved_path):
                    return True
        return False

    async def async_is_duplicate(self, sha256: str) -> bool:
        """Asynchronously check if file is duplicate."""
        return await asyncio.to_thread(self.is_duplicate, sha256)

    def rebuild_index(self) -> Tuple[int, int]:
        """Verify existence of physical files on disk and purge missing records.

        Returns:
            Tuple[int, int]: (cleaned_count, remaining_count)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, saved_path FROM file_metadata")
            rows = cursor.fetchall()

            missing_ids = [
                row["id"] for row in rows if not os.path.exists(row["saved_path"])
            ]

            cleaned_count = len(missing_ids)

            # Batch delete to respect SQLite parameter limits
            batch_size = 500
            for i in range(0, cleaned_count, batch_size):
                batch = missing_ids[i:i + batch_size]
                placeholders = ",".join("?" for _ in batch)
                conn.execute(
                    f"DELETE FROM file_metadata WHERE id IN ({placeholders})",
                    batch,
                )

            cursor.execute("SELECT COUNT(*) FROM file_metadata")
            remaining_count = cursor.fetchone()[0]

            conn.commit()
            return cleaned_count, remaining_count

    async def async_rebuild_index(self) -> Tuple[int, int]:
        """Asynchronously rebuild index and clean up records."""
        return await asyncio.to_thread(self.rebuild_index)
