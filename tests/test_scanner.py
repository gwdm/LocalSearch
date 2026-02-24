"""Tests for the file scanner."""

import os
import tempfile

from localsearch.config import Config
from localsearch.crawler.scanner import FileScanner
from localsearch.storage.metadb import MetadataDB


def test_scanner_finds_new_text_files():
    """Scanner should yield text files that aren't in the metadb."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        txt_path = os.path.join(tmpdir, "test.txt")
        with open(txt_path, "w") as f:
            f.write("hello world")

        pdf_path = os.path.join(tmpdir, "test.pdf")
        with open(pdf_path, "w") as f:
            f.write("fake pdf content")

        skip_path = os.path.join(tmpdir, "test.xyz")
        with open(skip_path, "w") as f:
            f.write("unsupported format")

        db_path = os.path.join(tmpdir, "meta.db")
        config = Config(scan_paths=[tmpdir])
        metadb = MetadataDB(db_path)

        scanner = FileScanner(config, metadb)
        results = list(scanner.scan([tmpdir]))

        found_paths = {r.path for r in results}
        assert str(os.path.realpath(txt_path)) in found_paths or any("test.txt" in p for p in found_paths)
        assert str(os.path.realpath(pdf_path)) in found_paths or any("test.pdf" in p for p in found_paths)
        # .xyz should not be found
        assert not any("test.xyz" in p for p in found_paths)

        metadb.close()


def test_scanner_skips_unchanged_files():
    """Scanner should not yield files already indexed with same mtime/size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "test.txt")
        with open(txt_path, "w") as f:
            f.write("hello world")

        db_path = os.path.join(tmpdir, "meta.db")
        config = Config(scan_paths=[tmpdir])
        metadb = MetadataDB(db_path)

        scanner = FileScanner(config, metadb)

        # First scan should find the file
        results1 = list(scanner.scan([tmpdir]))
        assert len(results1) == 1

        # Mark file as indexed
        stat = os.stat(txt_path)
        from localsearch.storage.metadb import FileRecord
        metadb.upsert_file(FileRecord(
            file_path=str(os.path.realpath(txt_path)),
            file_size=stat.st_size,
            mtime=stat.st_mtime,
            status="indexed",
        ))

        # Second scan should find nothing
        results2 = list(scanner.scan([tmpdir]))
        assert len(results2) == 0

        metadb.close()


def test_scanner_empty_directory():
    """Scanner should handle empty directories gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "meta.db")
        config = Config(scan_paths=[tmpdir])
        metadb = MetadataDB(db_path)

        scanner = FileScanner(config, metadb)
        results = list(scanner.scan([tmpdir]))
        assert len(results) == 0

        metadb.close()
