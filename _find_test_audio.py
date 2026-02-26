import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Find an audio file with error status that exists locally
print("=== FINDING TESTABLE AUDIO FILE ===\n")
c.execute("""
    SELECT file_path, error 
    FROM files 
    WHERE status=? 
      AND error LIKE '%Failed to transcribe audio%'
      AND (file_path LIKE '%.mp3' OR file_path LIKE '%.wav')
      AND file_path LIKE '%1-Msgs%'
    LIMIT 5
""", ('error',))

import os
for path, err in c.fetchall():
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    print(f"Path: {path}")
    print(f"Exists: {exists}")
    print(f"Size: {size:,} bytes")
    print(f"Error: {err[:100]}...")
    print("-" * 80)

conn.close()
