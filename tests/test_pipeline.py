"""Tests for the metadata database and config."""

import os
import tempfile

from localsearch.config import Config, load_config
from localsearch.storage.metadb import FileRecord, MetadataDB


def test_metadb_upsert_and_get():
    """MetadataDB should store and retrieve file records."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = MetadataDB(db_path)

        record = FileRecord(
            file_path="/test/file.txt",
            file_size=1234,
            mtime=1000.0,
            status="pending",
        )
        db.upsert_file(record)

        retrieved = db.get_file("/test/file.txt")
        assert retrieved is not None
        assert retrieved.file_size == 1234
        assert retrieved.mtime == 1000.0
        assert retrieved.status == "pending"

        db.close()


def test_metadb_is_changed():
    """is_changed should detect file modifications."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = MetadataDB(db_path)

        # New file should be considered changed
        assert db.is_changed("/new/file.txt", 100, 1000.0)

        # Add file
        db.upsert_file(FileRecord(
            file_path="/new/file.txt",
            file_size=100,
            mtime=1000.0,
            status="indexed",
        ))

        # Same file should not be changed
        assert not db.is_changed("/new/file.txt", 100, 1000.0)

        # Modified size
        assert db.is_changed("/new/file.txt", 200, 1000.0)

        # Modified mtime
        assert db.is_changed("/new/file.txt", 100, 2000.0)

        db.close()


def test_metadb_stats():
    """get_stats should return correct counts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = MetadataDB(db_path)

        db.upsert_file(FileRecord("/a.txt", 100, 1.0, status="indexed", chunk_count=5))
        db.upsert_file(FileRecord("/b.txt", 200, 2.0, status="indexed", chunk_count=3))
        db.upsert_file(FileRecord("/c.txt", 300, 3.0, status="error"))
        db.upsert_file(FileRecord("/d.txt", 400, 4.0, status="pending"))

        stats = db.get_stats()
        assert stats["total_files"] == 4
        assert stats["indexed"] == 2
        assert stats["errors"] == 1
        assert stats["pending"] == 1
        assert stats["total_chunks"] == 8

        db.close()


def test_config_defaults():
    """Config should have sensible defaults."""
    cfg = Config()
    assert cfg.qdrant.host == "localhost"
    assert cfg.qdrant.port == 6333
    assert cfg.embedding.model == "mixedbread-ai/mxbai-embed-large-v1"
    assert cfg.chunking.chunk_size == 1000
    assert ".txt" in cfg.extensions.text
    assert ".pdf" in cfg.extensions.pdf


def test_extensions_get_type():
    """ExtensionsConfig should correctly map extensions to types."""
    cfg = Config()
    assert cfg.extensions.get_type(".txt") == "text"
    assert cfg.extensions.get_type(".pdf") == "pdf"
    assert cfg.extensions.get_type(".mp3") == "audio"
    assert cfg.extensions.get_type(".mp4") == "video"
    assert cfg.extensions.get_type(".png") == "image"
    assert cfg.extensions.get_type(".docx") == "docx"
    assert cfg.extensions.get_type(".xyz") is None
