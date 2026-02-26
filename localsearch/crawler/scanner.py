"""Recursive file scanner with change detection."""

import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

from localsearch.config import Config
from localsearch.storage.metadb import FileRecord, MetadataDB
from localsearch.storage.progress import write_progress

# USN journal: only available natively on Windows
try:
    from localsearch.crawler.usn import (
        UsnJournal, JournalState, save_usn_state, load_usn_state,
    )
    _USN_AVAILABLE = True
except ImportError:
    _USN_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ScannedFile:
    path: str
    size: int
    mtime: float
    file_type: str
    extension: str


EXCLUDED_DIRS = {
    "$recycle.bin", "system volume information", "$windows.~bt",
    "$windows.~ws", "windows", "recovery", ".git", "__pycache__",
    "node_modules", ".venv", "venv",
}


class FileScanner:
    """Scans directories for files, detects changes against metadata DB."""

    def __init__(self, config: Config, metadb: MetadataDB):
        self.config = config
        self.metadb = metadb
        self.supported_extensions = config.extensions.all_extensions()
        self.max_file_size = config.scanner.max_file_size_mb * 1024 * 1024
        self.excluded_dirs = EXCLUDED_DIRS | {
            d.lower() for d in getattr(config.scanner, "exclude_dirs", [])
        }
        # Build sorted path_map so longest prefix matches first
        self._path_map = sorted(
            config.path_map.items(), key=lambda kv: len(kv[0]), reverse=True
        ) if config.path_map else []
        if self._path_map:
            logger.info("Path mapping active: %s", dict(self._path_map))

    def translate_path(self, file_path: str) -> str:
        """Apply path_map: replace container prefix with host prefix."""
        for container_prefix, host_prefix in self._path_map:
            if file_path.startswith(container_prefix):
                remainder = file_path[len(container_prefix):]
                # Strip leading separator to avoid double-slash/backslash
                remainder = remainder.lstrip("/\\")
                # Normalise separator: /foo → \\foo on Windows host paths
                if "\\" in host_prefix:
                    remainder = remainder.replace("/", "\\")
                # Ensure host_prefix ends with separator
                if host_prefix and not host_prefix.endswith(("/", "\\")):
                    host_prefix += "\\" if "\\" in host_prefix else "/"
                return host_prefix + remainder
        return file_path

    # ── USN journal helpers ────────────────────────────────────────────

    @property
    def _usn_enabled(self) -> bool:
        """Check if USN journal scanning is available and configured."""
        return (
            _USN_AVAILABLE
            and getattr(self.config.scanner, "use_usn_journal", True)
            and not self._path_map  # USN only for native (non-Docker) scans
        )

    @staticmethod
    def _drive_letter(path: str) -> Optional[str]:
        """Extract drive letter from a Windows path like 'D:/' or 'D:\\'."""
        p = str(path)
        if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
            return p[0].upper()
        return None

    def _try_usn_scan(self, scan_paths: list[str]) -> Optional[Generator[ScannedFile, None, None]]:
        """Attempt incremental scan via USN journal.

        Returns a generator of changed files, or None if USN is
        unavailable / state is missing (signals: fall back to full scan).
        """
        if not self._usn_enabled:
            return None

        # Group scan paths by drive letter
        drives: dict[str, list[str]] = {}
        for sp in scan_paths:
            dl = self._drive_letter(sp)
            if dl is None:
                logger.info("USN: scan path %s has no drive letter, falling back", sp)
                return None
            drives.setdefault(dl, []).append(os.path.normpath(sp).lower())

        # Check that every drive has saved USN state AND that we can
        # actually open the volume (requires Administrator privilege).
        for dl in drives:
            state = load_usn_state(self.config.metadata_db, dl)
            if state is None:
                logger.info("USN: no saved state for %s:, need full scan first", dl)
                return None
            try:
                with UsnJournal(dl) as journal:
                    journal.query()  # quick access check
            except OSError as e:
                logger.info("USN: cannot access %s: volume (%s), falling back to full scan", dl, e)
                return None

        return self._usn_incremental_scan(drives)

    def _usn_incremental_scan(
        self, drives: dict[str, list[str]]
    ) -> Generator[ScannedFile, None, None]:
        """Read USN journal changes and yield new/modified files."""
        total_changes = 0
        total_resolved = 0
        total_matched = 0

        for drive_letter, scan_prefixes in drives.items():
            saved = load_usn_state(self.config.metadata_db, drive_letter)
            if saved is None:
                continue

            try:
                with UsnJournal(drive_letter) as journal:
                    jstate = journal.query()

                    # Validate journal continuity
                    if jstate.journal_id != saved["journal_id"]:
                        logger.warning(
                            "USN: journal ID changed on %s: (was %d, now %d) — full scan needed",
                            drive_letter, saved["journal_id"], jstate.journal_id,
                        )
                        return

                    if saved["next_usn"] < jstate.first_usn:
                        logger.warning(
                            "USN: journal wrapped on %s: (saved USN %d < first_usn %d) — full scan needed",
                            drive_letter, saved["next_usn"], jstate.first_usn,
                        )
                        return

                    # Read changes since last scan
                    logger.info(
                        "USN: reading changes on %s: since USN %d (current %d)",
                        drive_letter, saved["next_usn"], jstate.next_usn,
                    )
                    changes = journal.read_changes(saved["next_usn"], jstate.journal_id)
                    total_changes += len(changes)

                    # Deduplicate by FRN (keep latest record per file)
                    by_frn: dict[int, object] = {}
                    for change in changes:
                        by_frn[change.file_reference_number] = change

                    logger.info(
                        "USN: %d raw changes, %d unique files on %s:",
                        len(changes), len(by_frn), drive_letter,
                    )

                    # Resolve FRN → path and check each file
                    for frn, change in by_frn.items():
                        if change.is_delete:
                            continue  # find_deleted() handles cleanup

                        path = journal.resolve_path(frn)
                        if path is None:
                            continue  # File deleted or inaccessible
                        total_resolved += 1

                        # Check if path falls under configured scan prefixes
                        norm_path = os.path.normpath(path).lower()
                        if not any(norm_path.startswith(pfx) for pfx in scan_prefixes):
                            continue

                        # Check extension, size, DB change status
                        scanned = self._check_path(path)
                        if scanned is not None:
                            total_matched += 1
                            yield scanned

                    # Save updated USN position AFTER processing
                    save_usn_state(self.config.metadata_db, drive_letter, jstate)

            except (OSError, RuntimeError) as e:
                logger.warning("USN: error reading journal on %s: — %s", drive_letter, e)
                return

        logger.info(
            "USN scan done: %d changes, %d resolved, %d new/changed files",
            total_changes, total_resolved, total_matched,
        )

    def _check_path(self, file_path: str) -> Optional[ScannedFile]:
        """Check a single file path (from USN) for processing eligibility.

        Same logic as _check_file() but works with a path string instead
        of an os.DirEntry.
        """
        ext = Path(file_path).suffix.lower()
        if ext not in self.supported_extensions:
            return None

        try:
            stat = os.stat(file_path)
        except OSError:
            return None

        if stat.st_size == 0:
            return None
        if stat.st_size > self.max_file_size:
            return None

        canonical = str(Path(file_path).resolve())

        if not self.metadb.is_changed(canonical, stat.st_size, stat.st_mtime):
            return None

        file_type = self.config.extensions.get_type(ext)
        if file_type is None:
            return None

        return ScannedFile(
            path=canonical,
            size=stat.st_size,
            mtime=stat.st_mtime,
            file_type=file_type,
            extension=ext,
        )

    def _save_usn_checkpoint(self, scan_paths: list[str]) -> None:
        """Save the current USN journal position for each drive in scan_paths.

        Called after a full scan completes so the next run can use USN.
        """
        if not self._usn_enabled:
            return

        seen_drives: set[str] = set()
        for sp in scan_paths:
            dl = self._drive_letter(sp)
            if dl is None or dl in seen_drives:
                continue
            seen_drives.add(dl)

            try:
                with UsnJournal(dl) as journal:
                    jstate = journal.query()
                    save_usn_state(self.config.metadata_db, dl, jstate)
            except (OSError, RuntimeError) as e:
                logger.warning("USN: cannot save checkpoint for %s: — %s", dl, e)

    def _reverse_translate_path(self, file_path: str) -> str:
        """Reverse path_map: replace host prefix with container prefix.
        
        Used when reading paths from USN log (which has host paths) to
        convert them to container paths that can be stat()ed inside Docker.
        """
        for container_prefix, host_prefix in self._path_map:
            # Normalize separators for comparison
            normalized_path = file_path.replace("\\", "/")
            normalized_host = host_prefix.replace("\\", "/").rstrip("/")
            
            if normalized_path.startswith(normalized_host):
                remainder = normalized_path[len(normalized_host):].lstrip("/")
                return container_prefix.rstrip("/") + "/" + remainder
        # No mapping found, return as-is
        return file_path

    def _scan_from_usn_log(self, log_file: Path) -> Generator[ScannedFile, None, None]:
        """Read file paths from permanent USN log and yield changed files.
        
        Log format: timestamp|action|path
        """
        self._scan_files_checked = 0
        self._scan_files_yielded = 0
        
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().strip().split("|", 2)
                if len(parts) != 3:
                    continue
                
                timestamp, action, file_path = parts
                self._scan_files_checked += 1
                
                # Reverse translate host path → container path for Docker
                container_path = self._reverse_translate_path(file_path)
                
                # Check if file exists and needs processing
                sf = self._check_single_file(Path(container_path))
                if sf is not None:
                    self._scan_files_yielded += 1
                    yield sf
        
        logger.info(
            "USN log scan: %d paths checked, %d new/changed",
            self._scan_files_checked, self._scan_files_yielded
        )

    # ── Main scan entry point ────────────────────────────────────────────

    def scan(self, paths: Optional[list[str]] = None) -> Generator[ScannedFile, None, None]:
        """Scan configured paths and yield new or changed files.

        Priority order:
        1. Permanent USN log file (if exists and not empty)
        2. NTFS USN journal for fast incremental detection
        3. Full directory walk (fallback)
        """
        scan_paths = paths or self.config.scan_paths
        if not scan_paths:
            logger.warning("No scan paths configured")
            return

        # ── Try permanent USN log first ──
        usn_log = Path(self.config.metadata_db).parent / "usn_changes.txt"
        if usn_log.exists() and usn_log.stat().st_size > 0:
            logger.info("Reading changes from permanent USN log: %s", usn_log)
            yield from self._scan_from_usn_log(usn_log)
            return

        # ── Try USN incremental scan ──
        usn_gen = self._try_usn_scan(scan_paths)
        if usn_gen is not None:
            logger.info("Using USN journal for incremental scan")
            self._scan_dirs_visited = 0
            self._scan_files_checked = 0
            self._scan_files_yielded = 0
            self._progress_last_write = time.monotonic()

            write_progress(
                self.config.metadata_db,
                phase="scanning", dirs_visited=0, files_checked=0, files_new=0,
                current_file="USN incremental",
            )

            for sf in usn_gen:
                self._scan_files_yielded += 1
                yield sf

            write_progress(
                self.config.metadata_db,
                files_new=self._scan_files_yielded,
                current_file="USN scan complete",
            )
            logger.info("USN incremental scan yielded %d files", self._scan_files_yielded)
            return

        # ── Full directory walk (fallback) ──
        logger.info("Using full directory walk")
        self._scan_dirs_visited = 0
        self._scan_files_checked = 0
        self._scan_files_yielded = 0
        self._progress_last_write = time.monotonic()

        write_progress(
            self.config.metadata_db,
            phase="scanning", dirs_visited=0, files_checked=0, files_new=0,
        )

        for scan_path in scan_paths:
            root = Path(scan_path)
            if not root.exists():
                logger.warning("Scan path does not exist: %s", scan_path)
                continue
            if root.is_file():
                # Single file passed via -p flag
                sf = self._check_single_file(root)
                if sf is not None:
                    self._scan_files_checked += 1
                    self._scan_files_yielded += 1
                    yield sf
                continue
            if not root.is_dir():
                logger.warning("Scan path is not a directory: %s", scan_path)
                continue

            logger.info("Scanning: %s", scan_path)
            yield from self._scan_directory(root)

        logger.info(
            "Scan walk finished: %d dirs visited, %d files checked, %d new/changed",
            self._scan_dirs_visited, self._scan_files_checked, self._scan_files_yielded,
        )
        write_progress(
            self.config.metadata_db,
            dirs_visited=self._scan_dirs_visited,
            files_checked=self._scan_files_checked,
            files_new=self._scan_files_yielded,
        )

        # Save USN checkpoint after full scan so next run uses USN
        self._save_usn_checkpoint(scan_paths)

    def _maybe_write_progress(self) -> None:
        """Write scan progress to JSON if enough dirs/files or time elapsed."""
        now = time.monotonic()
        if (self._scan_dirs_visited % 500 == 0 or
                self._scan_files_checked % 5000 == 0 or
                now - self._progress_last_write >= 15):
            self._progress_last_write = now
            logger.info(
                "Scan progress: %d dirs visited, %d files checked, %d new/changed",
                self._scan_dirs_visited, self._scan_files_checked, self._scan_files_yielded,
            )
            write_progress(
                self.config.metadata_db,
                dirs_visited=self._scan_dirs_visited,
                files_checked=self._scan_files_checked,
                files_new=self._scan_files_yielded,
            )

    def _scan_directory(self, root: Path) -> Generator[ScannedFile, None, None]:
        """Walk a directory tree and yield files that need processing."""
        self._scan_dirs_visited += 1
        self._maybe_write_progress()
        try:
            for entry in os.scandir(root):
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower() in self.excluded_dirs:
                            continue
                        yield from self._scan_directory(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        self._scan_files_checked += 1
                        if self._scan_files_checked % 5000 == 0:
                            self._maybe_write_progress()
                        scanned = self._check_file(entry)
                        if scanned is not None:
                            self._scan_files_yielded += 1
                            yield scanned
                except PermissionError:
                    logger.debug("Permission denied: %s", entry.path)
                except OSError as e:
                    logger.debug("OS error scanning %s: %s", entry.path, e)
        except PermissionError:
            logger.debug("Permission denied: %s", root)
        except OSError as e:
            logger.debug("OS error scanning directory %s: %s", root, e)

    def _check_single_file(self, path: Path) -> Optional[ScannedFile]:
        """Check a single file path (for -p flag with a file instead of dir)."""
        ext = path.suffix.lower()
        if ext not in self.supported_extensions:
            return None

        try:
            stat = path.stat()
        except OSError:
            return None

        if stat.st_size == 0:
            return None
        if stat.st_size > self.max_file_size:
            return None

        file_path = self.translate_path(str(path.resolve()))

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

        file_path = self.translate_path(str(Path(entry.path).resolve()))

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
        # Build translated scan prefixes for matching
        scan_prefixes = [
            self.translate_path(str(Path(sp).resolve())) for sp in scan_paths
        ]
        deleted = []

        for file_path in indexed_paths:
            # Only check files that fall under configured scan paths
            under_scan = any(
                file_path.startswith(prefix)
                for prefix in scan_prefixes
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
