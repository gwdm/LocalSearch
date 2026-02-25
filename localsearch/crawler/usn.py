"""NTFS USN (Update Sequence Number) Change Journal reader.

Provides fast incremental file change detection on Windows NTFS volumes
by reading the filesystem change journal instead of walking the directory tree.

Instead of calling os.scandir() on 460K+ files (minutes via Docker 9P,
30+ seconds even natively), this queries the NTFS journal for "what changed
since last scan?" and returns results in seconds regardless of file count.

Requirements:
  - Windows with NTFS volume
  - Read access to the volume (run as admin, or volume DACL allows it)
  - USN journal active (enabled by default on NTFS)

This module is only importable on Windows (raises ImportError otherwise).
"""

import sys

if sys.platform != "win32":
    raise ImportError("USN journal requires Windows NTFS")

import ctypes
import ctypes.wintypes as wintypes
import json
import logging
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Kernel32 setup ───────────────────────────────────────────────────────
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]

kernel32.DeviceIoControl.restype = wintypes.BOOL
kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]

kernel32.OpenFileById.restype = wintypes.HANDLE
kernel32.OpenFileById.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
]

kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
kernel32.GetFinalPathNameByHandleW.argtypes = [
    wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
]

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

# ── Windows constants ────────────────────────────────────────────────────
GENERIC_READ = 0x80000000
FILE_READ_ATTRIBUTES = 0x0080
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
FILE_SHARE_DELETE = 0x04
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

FSCTL_QUERY_USN_JOURNAL = 0x000900F4
FSCTL_READ_USN_JOURNAL = 0x000900BB

FILE_ATTRIBUTE_DIRECTORY = 0x10
ERROR_JOURNAL_NOT_ACTIVE = 1179
ERROR_HANDLE_EOF = 38

# ── USN Reason flags ────────────────────────────────────────────────────
USN_REASON_DATA_OVERWRITE = 0x00000001
USN_REASON_DATA_EXTEND = 0x00000002
USN_REASON_DATA_TRUNCATION = 0x00000004
USN_REASON_FILE_CREATE = 0x00000100
USN_REASON_FILE_DELETE = 0x00000200
USN_REASON_RENAME_OLD_NAME = 0x00001000
USN_REASON_RENAME_NEW_NAME = 0x00002000
USN_REASON_BASIC_INFO_CHANGE = 0x00008000
USN_REASON_CLOSE = 0x80000000

# Reasons indicating file content or metadata changed
CONTENT_CHANGE_REASONS = (
    USN_REASON_DATA_OVERWRITE | USN_REASON_DATA_EXTEND |
    USN_REASON_DATA_TRUNCATION | USN_REASON_FILE_CREATE |
    USN_REASON_FILE_DELETE | USN_REASON_RENAME_NEW_NAME |
    USN_REASON_BASIC_INFO_CHANGE
)

ALL_REASONS = CONTENT_CHANGE_REASONS | USN_REASON_CLOSE

# ── FILE_ID_DESCRIPTOR for OpenFileById ──────────────────────────────────
class _FILE_ID_UNION(ctypes.Union):
    _fields_ = [
        ("FileId", ctypes.c_longlong),
        ("ObjectId", ctypes.c_byte * 16),
    ]


class FILE_ID_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("Type", wintypes.DWORD),  # FILE_ID_TYPE enum: 0=FileIdType
        ("Id", _FILE_ID_UNION),
    ]


# ── Data classes ─────────────────────────────────────────────────────────
@dataclass
class JournalState:
    """Current state of the USN journal on a volume."""
    journal_id: int
    first_usn: int
    next_usn: int
    lowest_valid_usn: int
    max_usn: int


@dataclass
class UsnChange:
    """A parsed USN change record."""
    file_reference_number: int
    parent_file_reference_number: int
    usn: int
    reason: int
    file_attributes: int
    file_name: str
    is_directory: bool

    @property
    def is_delete(self) -> bool:
        return bool(self.reason & USN_REASON_FILE_DELETE)

    @property
    def is_create(self) -> bool:
        return bool(self.reason & USN_REASON_FILE_CREATE)

    @property
    def is_content_change(self) -> bool:
        return bool(self.reason & (
            USN_REASON_DATA_OVERWRITE | USN_REASON_DATA_EXTEND |
            USN_REASON_DATA_TRUNCATION))


# ── USN Journal Reader ──────────────────────────────────────────────────
class UsnJournal:
    """Read the NTFS USN change journal for a volume.

    Usage::

        with UsnJournal("D") as journal:
            state = journal.query()
            changes = journal.read_changes(saved_usn, state.journal_id)
            for change in changes:
                path = journal.resolve_path(change.file_reference_number)
                if path:
                    print(f"Changed: {path}")
    """

    def __init__(self, drive_letter: str):
        """Open a volume for USN journal access.

        Args:
            drive_letter: e.g. "D" (no colon or backslash)
        """
        self.drive_letter = drive_letter.rstrip(":\\")
        self._volume_handle: Optional[int] = None
        self._open_volume()

    def _open_volume(self) -> None:
        vol_path = f"\\\\.\\{self.drive_letter}:"
        # FSCTL_READ_USN_JOURNAL needs GENERIC_READ on the volume,
        # which requires running as Administrator.  When not elevated
        # the scanner falls back to a full directory walk automatically.
        handle = kernel32.CreateFileW(
            vol_path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            raise OSError(
                f"Cannot open volume {vol_path}: Windows error {err}. "
                f"USN journal requires running as Administrator."
            )
        self._volume_handle = handle

    def close(self) -> None:
        if self._volume_handle is not None and self._volume_handle != INVALID_HANDLE_VALUE:
            kernel32.CloseHandle(self._volume_handle)
            self._volume_handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def query(self) -> JournalState:
        """Query the current USN journal state (ID, position, bounds).

        Returns:
            JournalState with journal_id, first_usn, next_usn, etc.

        Raises:
            RuntimeError: If the USN journal is not active on this volume.
            OSError: On other Windows API errors.
        """
        # USN_JOURNAL_DATA_V0 = 7 × DWORDLONG = 56 bytes
        out_buf = ctypes.create_string_buffer(56)
        bytes_returned = wintypes.DWORD(0)

        ok = kernel32.DeviceIoControl(
            self._volume_handle,
            FSCTL_QUERY_USN_JOURNAL,
            None, 0,
            out_buf, 56,
            ctypes.byref(bytes_returned),
            None,
        )

        if not ok:
            err = ctypes.get_last_error()
            if err == ERROR_JOURNAL_NOT_ACTIVE:
                raise RuntimeError(
                    f"USN journal is not active on {self.drive_letter}:. "
                    f"Enable with: fsutil usn createjournal m=33554432 a=4194304 {self.drive_letter}:"
                )
            raise OSError(f"FSCTL_QUERY_USN_JOURNAL failed: Windows error {err}")

        fields = struct.unpack_from("<QQQQQQQ", out_buf.raw)
        return JournalState(
            journal_id=fields[0],
            first_usn=fields[1],
            next_usn=fields[2],
            lowest_valid_usn=fields[3],
            max_usn=fields[4],
        )

    def read_changes(
        self,
        since_usn: int,
        journal_id: int,
        reason_mask: int = ALL_REASONS,
    ) -> list[UsnChange]:
        """Read all journal changes since the given USN.

        Args:
            since_usn: Start reading from this USN position.
            journal_id: Expected journal ID (detects journal resets).
            reason_mask: Bitmask of USN_REASON_* flags to include.

        Returns:
            List of UsnChange records for changed files (not directories).
        """
        changes: list[UsnChange] = []
        current_usn = since_usn

        # Guard: if since_usn is before the oldest record still in the
        # journal, clamp to first_usn to avoid ERROR_JOURNAL_ENTRY_DELETED.
        state = self.query()
        if current_usn < state.first_usn:
            logger.warning(
                "USN since_usn %d is before first_usn %d — clamping",
                current_usn, state.first_usn,
            )
            current_usn = state.first_usn

        out_buf_size = 64 * 1024  # 64 KB read buffer
        out_buf = ctypes.create_string_buffer(out_buf_size)
        bytes_returned = wintypes.DWORD(0)

        while True:
            # READ_USN_JOURNAL_DATA_V0:
            #   StartUsn(8) + ReasonMask(4) + ReturnOnlyOnClose(4) +
            #   Timeout(8) + BytesToWaitFor(8) + UsnJournalID(8) = 40 bytes
            in_buf = struct.pack(
                "<qIIQQQ",
                current_usn,   # StartUsn
                reason_mask,   # ReasonMask
                0,             # ReturnOnlyOnClose = 0 (get all matching)
                0,             # Timeout
                0,             # BytesToWaitFor
                journal_id,    # UsnJournalID
            )

            ok = kernel32.DeviceIoControl(
                self._volume_handle,
                FSCTL_READ_USN_JOURNAL,
                in_buf, len(in_buf),
                out_buf, out_buf_size,
                ctypes.byref(bytes_returned),
                None,
            )

            if not ok:
                err = ctypes.get_last_error()
                if err == ERROR_HANDLE_EOF:
                    break  # No more data
                raise OSError(f"FSCTL_READ_USN_JOURNAL failed: Windows error {err}")

            returned = bytes_returned.value
            if returned <= 8:
                break  # Only the next-USN field, no records

            # First 8 bytes = next USN to continue reading from
            next_usn = struct.unpack_from("<q", out_buf.raw)[0]

            # Parse USN_RECORD_V2 entries starting at offset 8
            offset = 8
            while offset < returned:
                parsed = self._parse_usn_record(out_buf.raw, offset, returned)
                if parsed is None:
                    break
                record_length, change = parsed
                offset += record_length

                # Only yield file changes, not directory changes
                if change is not None and not change.is_directory:
                    changes.append(change)

            if next_usn <= current_usn:
                break  # No progress, avoid infinite loop
            current_usn = next_usn

        return changes

    def _parse_usn_record(
        self, data: bytes, offset: int, limit: int
    ) -> Optional[tuple[int, Optional[UsnChange]]]:
        """Parse a single USN_RECORD_V2 from a buffer.

        Returns:
            (record_length, UsnChange or None) or None if buffer exhausted.
        """
        # Need at least 60 bytes for the fixed-size header
        if offset + 60 > limit:
            return None

        # USN_RECORD_V2 layout:
        #  0: RecordLength        DWORD    4
        #  4: MajorVersion        WORD     2
        #  6: MinorVersion        WORD     2
        #  8: FileReferenceNumber DWORDLONG 8
        # 16: ParentFileRefNum    DWORDLONG 8
        # 24: Usn                 LONGLONG  8
        # 32: TimeStamp           LONGLONG  8
        # 40: Reason              DWORD    4
        # 44: SourceInfo          DWORD    4
        # 48: SecurityId          DWORD    4
        # 52: FileAttributes      DWORD    4
        # 56: FileNameLength      WORD     2
        # 58: FileNameOffset      WORD     2
        # 60: FileName[]          variable (UTF-16LE)

        record_length = struct.unpack_from("<I", data, offset)[0]
        if record_length < 60 or offset + record_length > limit:
            return None

        (
            rec_len, major_ver, minor_ver,
            frn, parent_frn, usn_val, timestamp,
            reason, source_info, security_id, file_attrs,
            name_len, name_offset,
        ) = struct.unpack_from("<IHHQQQQIIIIHH", data, offset)

        if major_ver != 2:
            # We only handle V2 records (standard NTFS)
            return (record_length, None)

        # Read filename (UTF-16LE)
        name_start = offset + name_offset
        name_end = name_start + name_len
        if name_end > limit:
            return (record_length, None)

        try:
            file_name = data[name_start:name_end].decode("utf-16-le")
        except UnicodeDecodeError:
            return (record_length, None)

        is_dir = bool(file_attrs & FILE_ATTRIBUTE_DIRECTORY)

        change = UsnChange(
            file_reference_number=frn,
            parent_file_reference_number=parent_frn,
            usn=usn_val,
            reason=reason,
            file_attributes=file_attrs,
            file_name=file_name,
            is_directory=is_dir,
        )

        return (record_length, change)

    def resolve_path(self, frn: int) -> Optional[str]:
        """Resolve a File Reference Number to a full file path.

        Uses OpenFileById + GetFinalPathNameByHandle.
        Returns None if the file no longer exists or can't be resolved.
        """
        fid = FILE_ID_DESCRIPTOR()
        fid.dwSize = ctypes.sizeof(FILE_ID_DESCRIPTOR)
        fid.Type = 0  # FileIdType
        fid.Id.FileId = frn

        file_handle = kernel32.OpenFileById(
            self._volume_handle,
            ctypes.byref(fid),
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            FILE_FLAG_BACKUP_SEMANTICS,
        )

        if file_handle == INVALID_HANDLE_VALUE:
            return None  # File deleted or inaccessible

        try:
            buf = ctypes.create_unicode_buffer(32768)
            length = kernel32.GetFinalPathNameByHandleW(file_handle, buf, 32768, 0)
            if length == 0:
                return None
            path = buf.value
            # Remove \\?\ prefix that GetFinalPathNameByHandle adds
            if path.startswith("\\\\?\\"):
                path = path[4:]
            return path
        finally:
            kernel32.CloseHandle(file_handle)


# ── State persistence ────────────────────────────────────────────────────
def _state_path(metadata_db: str) -> Path:
    """Derive USN state file path from metadata DB path."""
    return Path(metadata_db).parent / "usn_state.json"


def save_usn_state(
    metadata_db: str, drive_letter: str, journal_state: JournalState
) -> None:
    """Save USN journal state to a JSON file for the next incremental scan."""
    state_file = _state_path(metadata_db)

    # Load existing state (may track multiple volumes)
    existing: dict = {}
    if state_file.exists():
        try:
            existing = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    if "volumes" not in existing:
        existing["volumes"] = {}

    existing["volumes"][drive_letter.upper()] = {
        "journal_id": journal_state.journal_id,
        "next_usn": journal_state.next_usn,
        "saved_at": time.time(),
    }
    existing["last_save"] = time.time()

    state_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info(
        "Saved USN state for %s: journal_id=%d, next_usn=%d",
        drive_letter, journal_state.journal_id, journal_state.next_usn,
    )


def load_usn_state(metadata_db: str, drive_letter: str) -> Optional[dict]:
    """Load saved USN journal state for a drive.

    Returns:
        Dict with 'journal_id' and 'next_usn', or None if no state saved.
    """
    state_file = _state_path(metadata_db)
    if not state_file.exists():
        return None

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        vol = data.get("volumes", {}).get(drive_letter.upper())
        if vol and "journal_id" in vol and "next_usn" in vol:
            return vol
    except (json.JSONDecodeError, OSError):
        pass

    return None
