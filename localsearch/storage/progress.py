"""Lightweight JSON file for live ingest progress.

SQLite WAL mode does not work reliably across Docker bind mounts on
Windows (shared-memory mmap files don't cross the 9P boundary).  This
module writes/reads a tiny JSON file instead, using atomic rename to
avoid partial reads.

The file lives alongside the metadata DB (e.g. ``/data/ingest_progress.json``).
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT: dict = {
    "phase": "idle",
    "dirs_visited": 0,
    "files_checked": 0,
    "files_new": 0,
    "files_queued": 0,
    "files_processed": 0,
    "files_errors": 0,
    "current_file": "",
    "started_at": None,
    "updated_at": None,
    # Database stats (read from SQLite, cached in JSON for dashboard)
    "db_total": 0,
    "db_indexed": 0,
    "db_pending": 0,
    "db_errors": 0,
    "db_chunks": 0,
}


def _progress_path(metadata_db: str) -> Path:
    """Derive the progress JSON path from the metadata DB path."""
    return Path(metadata_db).parent / "ingest_progress.json"


def write_progress(metadata_db: str, **kwargs) -> None:
    """Atomically update the progress file.

    Reads the current state, merges *kwargs*, writes to a temp file,
    then renames over the target (atomic on both Linux and Windows).
    """
    path = _progress_path(metadata_db)
    data = read_progress(metadata_db)
    data.update(kwargs)
    data["updated_at"] = time.time()

    try:
        # Write to temp file in the same directory, then rename
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=".ingest_"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        # os.replace is atomic on POSIX; on Windows it's atomic if same volume
        os.replace(tmp, str(path))
    except Exception:
        logger.debug("Failed to write ingest progress", exc_info=True)
        # Clean up temp file if rename failed
        try:
            os.unlink(tmp)
        except Exception:
            pass


def read_progress(metadata_db: str) -> dict:
    """Read the current progress, returning defaults if file is missing."""
    path = _progress_path(metadata_db)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure all expected keys exist
        for key, val in _DEFAULT.items():
            data.setdefault(key, val)
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_DEFAULT)


def clear_progress(metadata_db: str) -> None:
    """Reset progress to idle."""
    write_progress(metadata_db, **_DEFAULT)


def update_db_stats(metadata_db: str) -> None:
    """Read current SQLite stats and write them to the progress JSON.
    
    This allows the dashboard to read stats from the JSON file
    without hitting database locks during heavy writes.
    """
    import sqlite3
    from pathlib import Path
    
    if not Path(metadata_db).exists():
        return
        
    try:
        conn = sqlite3.connect(metadata_db, timeout=1)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM files")
        total = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM files WHERE status='indexed'")
        indexed = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM files WHERE status IN ('pending','processing')")
        pending = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM files WHERE status='error'")
        errors = cur.fetchone()[0]
        
        cur.execute("SELECT COALESCE(SUM(chunk_count),0) FROM files WHERE status='indexed'")
        chunks = cur.fetchone()[0]
        
        conn.close()
        
        write_progress(
            metadata_db,
            db_total=total,
            db_indexed=indexed,
            db_pending=pending,
            db_errors=errors,
            db_chunks=chunks,
        )
    except Exception:
        logger.debug("Failed to update db stats in progress file", exc_info=True)

