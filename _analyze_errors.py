import sqlite3
conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()

# Total error count
c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
total = c.fetchone()[0]
print(f"Total errors: {total}\n")

# Top 20 distinct error messages
c.execute("SELECT error, COUNT(*) as cnt FROM files WHERE status='error' GROUP BY error ORDER BY cnt DESC LIMIT 20")
rows = c.fetchall()
for i, (err, cnt) in enumerate(rows, 1):
    pct = cnt / total * 100 if total else 0
    print(f"{i:>2}. [{cnt:>5}x] ({pct:5.1f}%)  {err[:200]}")

print(f"\n--- Sample file paths per error category (top 10) ---\n")
c.execute("SELECT error, COUNT(*) as cnt FROM files WHERE status='error' GROUP BY error ORDER BY cnt DESC LIMIT 10")
rows = c.fetchall()
for err, cnt in rows:
    c.execute("SELECT file_path FROM files WHERE status='error' AND error=? LIMIT 3", (err,))
    samples = [r[0] for r in c.fetchall()]
    short_err = err[:100] if err else "NULL"
    print(f"[{cnt}x] {short_err}")
    for s in samples:
        print(f"       {s}")
    print()

conn.close()
