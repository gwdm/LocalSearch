"""SQLite metadata database for tracking indexed files."""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FileRecord:
    file_path: str
    file_size: int
    mtime: float
    content_hash: Optional[str] = None
    status: str = "pending"
    indexed_at: Optional[float] = None
    chunk_count: int = 0
    error: Optional[str] = None


class MetadataDB:
    """SQLite database for tracking file indexing state."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_path TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                content_hash TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                indexed_at REAL,
                chunk_count INTEGER DEFAULT 0,
                error TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)
        """)
        conn.commit()

    def get_file(self, file_path: str) -> Optional[FileRecord]:
        """Get a file record by path."""
        row = self._get_conn().execute(
            "SELECT * FROM files WHERE file_path = ?", (file_path,)
        ).fetchone()
        if row is None:
            return None
        return FileRecord(
            file_path=row["file_path"],
            file_size=row["file_size"],
            mtime=row["mtime"],
            content_hash=row["content_hash"],
            status=row["status"],
            indexed_at=row["indexed_at"],
            chunk_count=row["chunk_count"],
            error=row["error"],
        )

    def upsert_file(self, record: FileRecord) -> None:
        """Insert or update a file record."""
        self._get_conn().execute("""
            INSERT INTO files (file_path, file_size, mtime, content_hash, status, indexed_at, chunk_count, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_size=excluded.file_size,
                mtime=excluded.mtime,
                content_hash=excluded.content_hash,
                status=excluded.status,
                indexed_at=excluded.indexed_at,
                chunk_count=excluded.chunk_count,
                error=excluded.error
        """, (
            record.file_path,
            record.file_size,
            record.mtime,
            record.content_hash,
            record.status,
            record.indexed_at,
            record.chunk_count,
            record.error,
        ))
        self._get_conn().commit()

    def mark_indexed(self, file_path: str, chunk_count: int) -> None:
        """Mark a file as successfully indexed."""
        self._get_conn().execute("""
            UPDATE files SET status='indexed', indexed_at=?, chunk_count=?, error=NULL
            WHERE file_path=?
        """, (time.time(), chunk_count, file_path))
        self._get_conn().commit()

    def mark_error(self, file_path: str, error: str) -> None:
        """Mark a file as having an indexing error."""
        self._get_conn().execute("""
            UPDATE files SET status='error', error=? WHERE file_path=?
        """, (error, file_path))
        self._get_conn().commit()

    def is_changed(self, file_path: str, file_size: int, mtime: float) -> bool:
        """Check if a file has changed since last indexing."""
        existing = self.get_file(file_path)
        if existing is None:
            return True
        if existing.status == "error":
            return True
        return existing.file_size != file_size or existing.mtime != mtime

    def get_all_indexed_paths(self) -> set[str]:
        """Get all file paths currently tracked in the database."""
        rows = self._get_conn().execute(
            "SELECT file_path FROM files"
        ).fetchall()
        return {row["file_path"] for row in rows}

    def remove_file(self, file_path: str) -> None:
        """Remove a file record from the database."""
        self._get_conn().execute(
            "DELETE FROM files WHERE file_path = ?", (file_path,)
        )
        self._get_conn().commit()

    def remove_files(self, file_paths: list[str]) -> None:
        """Remove multiple file records in a batch."""
        conn = self._get_conn()
        conn.executemany(
            "DELETE FROM files WHERE file_path = ?",
            [(p,) for p in file_paths],
        )
        conn.commit()

    def get_stats(self) -> dict:
        """Get indexing statistics."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM files WHERE status='indexed'").fetchone()[0]
        errors = conn.execute("SELECT COUNT(*) FROM files WHERE status='error'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM files WHERE status='pending'").fetchone()[0]
        total_chunks = conn.execute("SELECT COALESCE(SUM(chunk_count), 0) FROM files WHERE status='indexed'").fetchone()[0]
        return {
            "total_files": total,
            "indexed": indexed,
            "errors": errors,
            "pending": pending,
            "total_chunks": total_chunks,
        }

    def clear(self) -> None:
        """Delete all records."""
        self._get_conn().execute("DELETE FROM files")
        self._get_conn().commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
