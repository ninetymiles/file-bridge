"""SQLite metadata store for tracking received files and deduplication."""

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

CURRENT_SCHEMA_VERSION = 1


class UnsupportedSchemaVersion(RuntimeError):
    """Raised when the database was created by a different schema version."""

    def __init__(self, db_path: str, found_version: int, supported_version: int):
        super().__init__(
            f"Unsupported database schema version {found_version} at {db_path}; "
            f"this build supports version {supported_version} only. "
            "Delete the database file and restart to reinitialize it."
        )
        self.db_path = db_path
        self.found_version = found_version
        self.supported_version = supported_version


@dataclass(frozen=True)
class DailyStatistics:
    """Files and distinct senders recorded on one calendar day."""

    day: str
    users: int
    files: int


@dataclass(frozen=True)
class IndexStatistics:
    """Aggregated index facts consumed by the report renderer."""

    total_files: int
    total_users: int
    typed_counts: Dict[str, int]
    null_saved_paths: Tuple[str, ...]
    daily: Tuple[DailyStatistics, ...]


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
        """Create a new database at the current schema version, or validate an existing one."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        is_new_db = not os.path.exists(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            if not is_new_db:
                version = conn.execute("PRAGMA user_version;").fetchone()[0]
                if version != CURRENT_SCHEMA_VERSION:
                    raise UnsupportedSchemaVersion(
                        self.db_path, version, CURRENT_SCHEMA_VERSION
                    )
                return

            conn.execute("PRAGMA journal_mode=WAL;")
            # DDL and the version stamp must land atomically: a half-initialized
            # file would read as version 0 and be refused on the next startup.
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute("""
                CREATE TABLE file_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id TEXT NOT NULL,
                    sender_nick TEXT,
                    created_at TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    saved_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_size INTEGER,
                    media_type TEXT
                );
            """)
            conn.execute("CREATE INDEX idx_file_sha256 ON file_metadata(sha256);")
            conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION};")
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
        media_type: Optional[str] = None,
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
                    sender_id, sender_nick, created_at, original_filename, saved_path, sha256, file_size, media_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sender_id, sender_nick, created_at, original_filename, saved_path, sha256, file_size, media_type),
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
        media_type: Optional[str] = None,
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
            media_type,
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

    def get_index_statistics(self) -> IndexStatistics:
        """Aggregate report facts without loading the whole table into memory."""
        with self.get_connection() as conn:
            total_files = conn.execute(
                "SELECT COUNT(*) FROM file_metadata"
            ).fetchone()[0]
            total_users = conn.execute(
                "SELECT COUNT(DISTINCT sender_id) FROM file_metadata"
            ).fetchone()[0]
            typed_counts = {
                row["media_type"]: row["count"]
                for row in conn.execute(
                    """
                    SELECT media_type, COUNT(*) AS count
                    FROM file_metadata
                    WHERE media_type IS NOT NULL
                    GROUP BY media_type
                    """
                )
            }
            null_saved_paths = tuple(
                row["saved_path"]
                for row in conn.execute(
                    "SELECT saved_path FROM file_metadata WHERE media_type IS NULL"
                )
            )
            daily = tuple(
                DailyStatistics(
                    day=row["day"], users=row["users"], files=row["files"]
                )
                for row in conn.execute(
                    """
                    SELECT date(created_at) AS day,
                           COUNT(DISTINCT sender_id) AS users,
                           COUNT(*) AS files
                    FROM file_metadata
                    GROUP BY day
                    ORDER BY day DESC
                    """
                )
            )

        return IndexStatistics(
            total_files=total_files,
            total_users=total_users,
            typed_counts=typed_counts,
            null_saved_paths=null_saved_paths,
            daily=daily,
        )

    async def async_get_index_statistics(self) -> IndexStatistics:
        """Asynchronously aggregate report facts."""
        return await asyncio.to_thread(self.get_index_statistics)
