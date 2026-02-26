"""RAM disk lifecycle management for LocalSearch.

Automatically creates/destroys RAM disk based on available system memory.
Falls back to disk caching if insufficient RAM available.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RAMDiskManager:
    """Manages RAM disk creation and teardown for database performance."""

    def __init__(self, db_path: str, drive_letter: str = "Z"):
        """
        Args:
            db_path: Path to localsearch_meta.db
            drive_letter: Windows drive letter for RAM disk (default Z:)
        """
        self.db_path = db_path
        self.drive_letter = drive_letter.upper()
        self.ramdisk_mount = f"{self.drive_letter}:"
        self.ramdisk_db_path = f"{self.ramdisk_mount}\\localsearch_meta.db"
        self.is_active = False
        self.fallback_to_cache = False

    @staticmethod
    def get_available_ram_mb() -> int:
        """Get available RAM in MB."""
        try:
            if sys.platform == "win32":
                import psutil
                return int(psutil.virtual_memory().available / (1024 * 1024))
            else:
                import psutil
                return int(psutil.virtual_memory().available / (1024 * 1024))
        except Exception as e:
            logger.warning("Could not detect available RAM: %s, using 8GB default", e)
            return 8192

    @staticmethod
    def get_total_ram_mb() -> int:
        """Get total system RAM in MB."""
        try:
            import psutil
            return int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception:
            return 16384  # default assumption

    def calculate_ramdisk_size_mb(self) -> int:
        """Calculate optimal RAM disk size based on available memory.

        Returns:
            Size in MB, or 0 if insufficient memory (will use caching).
        """
        available = self.get_available_ram_mb()
        total = self.get_total_ram_mb()

        # Need at least 25GB total RAM, keep 50% free for OS
        min_ram_required = 25 * 1024  # 25GB
        if total < min_ram_required:
            logger.warning(
                "System RAM (%d GB) below LocalSearch minimum (%d GB). "
                "Using disk caching instead of RAM disk.",
                total // 1024, min_ram_required // 1024
            )
            return 0

        # Allocate up to 20GB if available (but leave 4GB for OS)
        os_reserve = 4 * 1024  # 4GB minimum for OS
        max_ramdisk = 20 * 1024  # 20GB max for DB
        available_for_ramdisk = available - os_reserve

        if available_for_ramdisk < 2 * 1024:  # Less than 2GB available
            logger.warning(
                "Only %d MB RAM available (need %d MB for optimal RAM disk). "
                "Using disk caching instead.",
                available_for_ramdisk, 2 * 1024
            )
            return 0

        ramdisk_size = min(max_ramdisk, available_for_ramdisk)
        logger.info(
            "System RAM: %d GB total, %d MB available → RAM disk: %d MB",
            total // 1024, available_for_ramdisk, ramdisk_size
        )
        return ramdisk_size

    def create(self) -> bool:
        """Create RAM disk and copy database.

        Returns:
            True if successful, False if fallback to caching.
        """
        ramdisk_size_mb = self.calculate_ramdisk_size_mb()

        if ramdisk_size_mb == 0:
            logger.info("Using disk caching (insufficient RAM for RAM disk)")
            self.fallback_to_cache = True
            return False

        # Check if RAM disk already exists
        if Path(self.ramdisk_mount).exists():
            logger.info("RAM disk already exists at %s", self.ramdisk_mount)
            self.is_active = True
            return True

        # Create RAM disk (Windows only)
        logger.info("Creating %d MB RAM disk at %s:", ramdisk_size_mb, self.ramdisk_mount)
        try:
            result = subprocess.run(
                [
                    "imdisk", "-a",
                    "-s", f"{ramdisk_size_mb}M",
                    "-m", self.ramdisk_mount,
                    "-p", "/fs:ntfs"
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "imdisk failed (code %d): %s. Falling back to caching.",
                    result.returncode, result.stderr
                )
                self.fallback_to_cache = True
                return False
        except FileNotFoundError:
            logger.warning(
                "imdisk not found. Install imdisk toolkit or use disk caching. "
                "Download: https://sourceforge.net/projects/imdisk-toolkit/"
            )
            self.fallback_to_cache = True
            return False
        except Exception as e:
            logger.warning("RAM disk creation failed: %s. Using disk caching.", e)
            self.fallback_to_cache = True
            return False

        # Copy database to RAM disk if it exists
        if Path(self.db_path).exists():
            logger.info("Copying database to RAM disk...")
            try:
                shutil.copy2(self.db_path, self.ramdisk_db_path)
                logger.info("✓ Database copied to RAM disk")
            except Exception as e:
                logger.warning("Failed to copy database: %s", e)
                # Continue anyway, will create new DB
        else:
            logger.info("No existing database, will create new one on RAM disk")

        self.is_active = True
        logger.info("✓ RAM disk ready at %s", self.ramdisk_mount)
        return True

    def destroy(self) -> bool:
        """Copy database back to disk and destroy RAM disk.

        Returns:
            True if successful.
        """
        if not self.is_active:
            logger.debug("RAM disk not active, skipping destroy")
            return True

        if self.fallback_to_cache:
            logger.info("Using disk caching (no RAM disk to destroy)")
            return True

        logger.info("Finalizing RAM disk...")

        # Copy database back to disk
        if Path(self.ramdisk_db_path).exists():
            logger.info("Copying database from RAM to disk...")
            try:
                backup_dir = Path(self.db_path).parent
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.ramdisk_db_path, self.db_path)
                logger.info("✓ Database copied to %s", self.db_path)
            except Exception as e:
                logger.error("Failed to copy database from RAM: %s", e)
                return False

        # Unmount RAM disk
        logger.info("Removing RAM disk...")
        try:
            result = subprocess.run(
                ["imdisk", "-d", "-m", self.ramdisk_mount],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info("✓ RAM disk removed")
                self.is_active = False
                return True
            else:
                logger.warning(
                    "Failed to remove RAM disk (code %d): %s. "
                    "You may need to remove it manually.",
                    result.returncode, result.stderr
                )
                return False
        except Exception as e:
            logger.warning(
                "Error removing RAM disk: %s. "
                "You may need to remove it manually with: imdisk -d -m %s",
                e, self.ramdisk_mount
            )
            return False

    def get_db_path(self) -> str:
        """Get the database path to use (RAM disk or disk).

        Returns:
            Path to use for metadata_db config.
        """
        if self.is_active and not self.fallback_to_cache:
            return self.ramdisk_db_path
        return self.db_path
