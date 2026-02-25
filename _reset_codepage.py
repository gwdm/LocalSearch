import sqlite3
conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM files WHERE status='error' AND error LIKE '%code page%'")
cnt = c.fetchone()[0]
print(f"Code page errors to reset: {cnt}")

c.execute("UPDATE files SET status='pending', error=NULL WHERE status='error' AND error LIKE '%code page%'")
print(f"Reset {c.rowcount} files to pending")

c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
print(f"Remaining errors: {c.fetchone()[0]}")

conn.commit()
conn.close()
