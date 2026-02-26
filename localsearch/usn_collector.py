"""USN Journal collector - reads changes and appends to permanent log.

This runs:
- Daily (scheduled task)
- At system startup
- Before every ingestion

It reads the NTFS USN journal and appends new changes to a permanent file
that survives journal wraparound.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from localsearch.config import load_config

logger = logging.getLogger(__name__)


def collect_changes(config_path: str = None, output_file: str = None) -> int:
    """Read USN journal and append changes to permanent log.
    
    Args:
        config_path: Path to config file
        output_file: Output file path (overrides default)
        
    Returns:
        Number of changes appended
    """
    # Import USN journal only when collecting (requires Windows)
    from localsearch.crawler.usn import UsnJournal, load_usn_state, save_usn_state
    
    cfg = load_config(config_path)
    
    if output_file is None:
        output_file = str(Path(cfg.metadata_db).parent / "usn_changes.txt")
    
    # Get scan paths and extract drive letters
    drives = set()
    for scan_path in cfg.scan_paths:
        p = str(scan_path)
        if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
            drives.add(p[0].upper())
    
    if not drives:
        logger.error("No valid drive letters found in scan_paths")
        return 0
    
    total_changes = 0
    timestamp = datetime.now().isoformat()
    
    # Open output file in append mode
    with open(output_file, "a", encoding="utf-8") as f:
        for drive_letter in sorted(drives):
            # Load last USN state
            state = load_usn_state(cfg.metadata_db, drive_letter)
            
            if state is None:
                logger.warning(
                    "No USN state for %s:, run initial scan first", drive_letter
                )
                continue
            
            try:
                journal = UsnJournal(drive_letter)
                changes = list(journal.read_changes(state.last_usn))
                
                if not changes:
                    logger.info("No changes on %s:", drive_letter)
                    continue
                
                # Write changes to permanent log
                for change in changes:
                    # Format: timestamp|action|path
                    f.write(f"{timestamp}|{change.action}|{change.path}\n")
                    total_changes += 1
                
                # Update USN state
                new_usn = max(c.usn for c in changes)
                state.last_usn = new_usn
                save_usn_state(cfg.metadata_db, drive_letter, state)
                
                logger.info(
                    "Collected %d changes from %s: (USN: %d → %d)",
                    len(changes), drive_letter, state.last_usn, new_usn
                )
                
            except Exception as e:
                logger.error("Failed to read USN journal for %s: %s", drive_letter, e)
                continue
    
    logger.info("Total changes collected: %d (written to %s)", total_changes, output_file)
    return total_changes


def trim_processed(config_path: str = None, input_file: str = None, processed_paths: set = None) -> int:
    """Remove processed entries from the permanent log.
    
    Args:
        config_path: Path to config file
        input_file: Input file path (overrides default)
        processed_paths: Set of file paths that have been processed
        
    Returns:
        Number of entries removed
    """
    cfg = load_config(config_path)
    
    if input_file is None:
        input_file = str(Path(cfg.metadata_db).parent / "usn_changes.txt")
    
    if not Path(input_file).exists():
        return 0
    
    if processed_paths is None:
        processed_paths = set()
    
    # Read all entries
    kept_lines = []
    removed_count = 0
    
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|", 2)
            if len(parts) == 3:
                timestamp, action, path = parts
                if path not in processed_paths:
                    kept_lines.append(line)
                else:
                    removed_count += 1
    
    # Rewrite file with remaining entries
    with open(input_file, "w", encoding="utf-8") as f:
        f.writelines(kept_lines)
    
    logger.info(
        "Trimmed %d processed entries from %s (%d remaining)",
        removed_count, input_file, len(kept_lines)
    )
    return removed_count


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    
    if len(sys.argv) > 1 and sys.argv[1] == "--trim":
        # Trim mode (used after ingestion)
        count = trim_processed()
        print(f"Trimmed {count} entries")
    else:
        # Collect mode (default)
        count = collect_changes()
        print(f"Collected {count} changes")
