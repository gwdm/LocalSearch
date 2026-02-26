#!/usr/bin/env python3
"""Detailed check of error file state."""
import sqlite3

db_path = r"D:\OneDrive\1_Python_REPOS\0-PROJECTS\LocalSearch\data\localsearch_meta.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Get all status counts
c.execute("SELECT status, COUNT(*) FROM files GROUP BY status")
print("Status counts:")
for status, count in c.fetchall():
    print(f"  {status}: {count:,}")
print()

# Check error files indexed_at status
c.execute("SELECT COUNT(*) FROM files WHERE status='error' AND indexed_at IS NULL")
null_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files WHERE status='error' AND indexed_at IS NOT NULL")
notnull_count = c.fetchone()[0]
print(f"Error files with indexed_at NULL: {null_count}")
print(f"Error files with indexed_at NOT NULL: {notnull_count}")
print()

# Show a few error samples
c.execute("""
    SELECT file_path, indexed_at, error
    FROM files
    WHERE status='error'
    LIMIT 5
""")
print("Sample error files:")
for file_path, indexed_at, error in c.fetchall():
    print(f"  indexed_at: {indexed_at}")
    print(f"  path: {file_path[:60]}")
    print(f"  error: {error[:60]}")
    print()

conn.close()
