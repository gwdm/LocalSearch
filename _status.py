import sqlite3, time
conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()

# Snapshot 1
c.execute("SELECT COUNT(*) FROM files WHERE status='indexed'")
idx1 = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
err1 = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files WHERE status='pending'")
pend1 = c.fetchone()[0]
c.execute("SELECT COALESCE(SUM(chunk_count),0) FROM files WHERE status='indexed'")
chunks = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files")
total = c.fetchone()[0]

time.sleep(30)

# Snapshot 2
c.execute("SELECT COUNT(*) FROM files WHERE status='indexed'")
idx2 = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
err2 = c.fetchone()[0]

dt = 30
rate = (idx2 - idx1 + err2 - err1) / dt

# Last 5 indexed
c.execute("SELECT file_path FROM files WHERE status='indexed' ORDER BY indexed_at DESC LIMIT 5")
recent = [r[0] for r in c.fetchall()]

print(f"=== LocalSearch Pipeline Status ===")
print(f"Total tracked:  {total:,}")
print(f"Indexed:        {idx2:,}  (+{idx2-idx1} in {dt}s)")
print(f"Errors:         {err2:,}  (+{err2-err1} in {dt}s)")
print(f"Pending:        {pend1:,}")
print(f"Total chunks:   {chunks:,}")
print(f"Processing rate: {rate:.1f} files/s")
if rate > 0:
    eta_h = pend1 / rate / 3600
    print(f"ETA (pending):  ~{eta_h:.1f} hours")
print(f"\nLast indexed files:")
for f in recent:
    print(f"  {f}")
conn.close()
