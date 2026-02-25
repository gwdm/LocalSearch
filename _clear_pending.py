"""One-shot script: clear stale 'pending' records from metadb."""
import sqlite3

db_path = "data/localsearch_meta.db"
conn = sqlite3.connect(db_path)
pending = conn.execute("SELECT COUNT(*) FROM files WHERE status='pending'").fetchone()[0]
print(f"Pending records: {pending}")
conn.execute("DELETE FROM files WHERE status='pending'")
conn.commit()
total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
print(f"Cleared {pending} stale pending records")
print(f"Total records remaining: {total}")
conn.close()
