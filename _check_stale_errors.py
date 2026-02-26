#!/usr/bin/env python3
"""Check if pending files have stale error messages."""
import sqlite3

db_path = r"D:\OneDrive\1_Python_REPOS\0-PROJECTS\LocalSearch\data\localsearch_meta.db"
conn = sqlite3.connect(db_path)

# Status counts
print("Status counts:")
for status, count in conn.execute("SELECT status, COUNT(*) FROM files GROUP BY status").fetchall():
    print(f"  {status}: {count:,}")
print()

# Check for pending files with error messages (should be 0)
pending_with_errors = conn.execute(
    "SELECT COUNT(*) FROM files WHERE status='pending' AND error IS NOT NULL AND error != ''"
).fetchone()[0]

print(f"Pending files with error messages: {pending_with_errors}")

if pending_with_errors > 0:
    print("\nSample pending files with errors:")
    for file_path, error in conn.execute(
        "SELECT file_path, error FROM files WHERE status='pending' AND error IS NOT NULL LIMIT 5"
    ).fetchall():
        print(f"  {file_path[:60]}")
        print(f"    Error: {error[:60]}")
        print()

# Check indexed files with error messages (should be 0)
indexed_with_errors = conn.execute(
    "SELECT COUNT(*) FROM files WHERE status='indexed' AND error IS NOT NULL AND error != ''"
).fetchone()[0]

print(f"Indexed files with error messages: {indexed_with_errors}")

conn.close()
