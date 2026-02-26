import sqlite3, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
db = "data/localsearch_meta.db"
if not os.path.exists(db):
    print("Database not found!"); exit()
conn = sqlite3.connect(db)
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM files WHERE status='indexed'")
idx = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
err = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files WHERE status='pending'")
pend = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files")
total = c.fetchone()[0]
c.execute("SELECT COALESCE(SUM(chunk_count),0) FROM files WHERE status='indexed'")
chunks = c.fetchone()[0]
c.execute("SELECT file_path FROM files WHERE status='indexed' ORDER BY indexed_at DESC LIMIT 5")
recent = [r[0] for r in c.fetchall()]
c.execute("SELECT file_path FROM files WHERE status='error' ORDER BY indexed_at DESC LIMIT 5")
recent_err = [r[0] for r in c.fetchall()]
print(f"=== LocalSearch Status ===")
print(f"Total tracked:  {total:,}")
print(f"Indexed:        {idx:,}")
print(f"Pending:        {pend:,}")
print(f"Errors:         {err:,}")
print(f"Total chunks:   {chunks:,}")
print()
print("Last indexed:")
for f in recent:
    print(f"  {f}")
if recent_err:
    print()
    print("Recent errors:")
    for f in recent_err:
        print(f"  {f}")
conn.close()
