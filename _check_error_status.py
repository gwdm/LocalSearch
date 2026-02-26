#!/usr/bin/env python3
"""Check status of files with specific error messages."""
import sqlite3

db_path = r"D:\OneDrive\1_Python_REPOS\0-PROJECTS\LocalSearch\data\localsearch_meta.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Get some specific error files and their status
c.execute("""
    SELECT file_path, status, error
    FROM files
    WHERE error LIKE '%No text detected in image%'
    LIMIT 10
""")

print("Sample error files status:")
for file_path, status, error in c.fetchall():
    print(f"  Status: {status}")
    print(f"  Path: {file_path}")
    print(f"  Error: {error[:80] if error else ''}...")
    print()

# Count by status
c.execute("""
    SELECT status, COUNT(*)
    FROM files
    WHERE error IS NOT NULL AND error != ''
    GROUP BY status
""")

print("\nFiles with error messages, grouped by status:")
for status, count in c.fetchall():
    print(f"  {status}: {count}")

conn.close()
