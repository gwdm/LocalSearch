"""Recursive file scanner with change detection."""

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

from localsearch.config import Config
from localsearch.storage.metadb import FileRecord, MetadataDB

logger = logging.getLogger(__name__)


@dataclass
class ScannedFile:
    path: str
    size: int
    mtime: float
    file_type: str
    extension: str


class FileScanner:
    """Scans directories for files, detects changes against metadata DB."""

    def __init__(self, config: Config, metadb: MetadataDB):
        self.config = config
        self.metadb = metadb
        self.supported_extensions = config.extensions.all_extensions()
        self.max_file_size = config.scanner.max_file_size_mb * 1024 * 1024

    def scan(self, paths: Optional[list[str]] = None) -> Generator[ScannedFile, None, None]:
        """Scan configured paths and yield new or changed files.

        Uses a generator to handle millions of files without loading
        all into memory.
        """
        scan_paths = paths or self.config.scan_paths
        if not scan_paths:
            logger.warning("No scan paths configured")
            return

        for scan_path in scan_paths:
            root = Path(scan_path)
            if not root.exists():
                logger.warning("Scan path does not exist: %s", scan_path)
                continue
            if not root.is_dir():
                logger.warning("Scan path is not a directory: %s", scan_path)
                continue

            logger.info("Scanning: %s", scan_path)
            yield from self._scan_directory(root)

    def _scan_directory(self, root: Path) -> Generator[ScannedFile, None, None]:
        """Walk a directory tree and yield files that need processing."""
        try:
            for entry in os.scandir(root):
                try:
                    if entry.is_dir(follow_symlinks=False):
                        yield from self._scan_directory(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        scanned = self._check_file(entry)
                        if scanned is not None:
                            yield scanned
                except PermissionError:
                    logger.debug("Permission denied: %s", entry.path)
                except OSError as e:
                    logger.debug("OS error scanning %s: %s", entry.path, e)
        except PermissionError:
            logger.debug("Permission denied: %s", root)
        except OSError as e:
            logger.debug("OS error scanning directory %s: %s", root, e)

    def _check_file(self, entry: os.DirEntry) -> Optional[ScannedFile]:
        """Check if a file should be processed."""
        ext = Path(entry.name).suffix.lower()
        if ext not in self.supported_extensions:
            return None

        try:
            stat = entry.stat()
        except OSError:
            return None

        if stat.st_size == 0:
            return None
        if stat.st_size > self.max_file_size:
            logger.debug("Skipping large file (%d MB): %s",
                         stat.st_size // (1024 * 1024), entry.path)
            return None

        file_path = str(Path(entry.path).resolve())

        if not self.metadb.is_changed(file_path, stat.st_size, stat.st_mtime):
            return None

        file_type = self.config.extensions.get_type(ext)
        if file_type is None:
            return None

        return ScannedFile(
            path=file_path,
            size=stat.st_size,
            mtime=stat.st_mtime,
            file_type=file_type,
            extension=ext,
        )

    def find_deleted(self, paths: Optional[list[str]] = None) -> list[str]:
        """Find files in the metadata DB that no longer exist on disk."""
        indexed_paths = self.metadb.get_all_indexed_paths()
        scan_paths = paths or self.config.scan_paths
        deleted = []

        for file_path in indexed_paths:
            # Only check files that fall under configured scan paths
            under_scan = any(
                file_path.startswith(str(Path(sp).resolve()))
                for sp in scan_paths
            )
            if under_scan and not Path(file_path).exists():
                deleted.append(file_path)

        return deleted


def compute_content_hash(file_path: str, block_size: int = 65536) -> str:
    """Compute SHA-256 hash of file contents."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()
