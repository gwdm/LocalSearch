#!/usr/bin/env python3
"""Check when error files were last processed."""
import sqlite3
from datetime import datetime

db_path = r"D:\OneDrive\1_Python_REPOS\0-PROJECTS\LocalSearch\data\localsearch_meta.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Get all error files sorted by indexed_at (most recent first)
c.execute("""
    SELECT file_path, indexed_at, error
    FROM files
    WHERE status = 'error'
    ORDER BY indexed_at DESC
    LIMIT 20
""")

print("Most recently processed error files:")
for file_path, indexed_at, error in c.fetchall():
    if indexed_at:
        dt = datetime.fromtimestamp(indexed_at)
        print(f"  {dt}: {error[:60]}...")
    else:
        print(f"  [never indexed]: {error[:60]}...")

# Count errors by timestamp ranges
print("\nError files by last processed time:")
now = datetime.now().timestamp()
hour_ago = now - 3600
day_ago = now - 86400

c.execute("""
    SELECT 
        CASE 
            WHEN indexed_at IS NULL THEN 'Never processed'
            WHEN indexed_at > ? THEN 'Last hour'
            WHEN indexed_at > ? THEN 'Last day'
            ELSE 'Older'
        END as timerange,
        COUNT(*)
    FROM files
    WHERE status = 'error'
    GROUP BY timerange
""", (hour_ago, day_ago))

for timerange, count in c.fetchall():
    print(f"  {timerange}: {count}")

conn.close()
