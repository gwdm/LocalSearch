import sqlite3
conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM files WHERE status='error' AND error LIKE '%has no attribute%message%'")
msg_errs = c.fetchone()[0]
print(f"MSG attribute errors to reset: {msg_errs}")

c.execute("UPDATE files SET status='pending', error=NULL WHERE status='error' AND error LIKE '%has no attribute%message%'")
print(f"Reset {c.rowcount} files to pending")

c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
print(f"Remaining errors: {c.fetchone()[0]}")

c.execute("SELECT COUNT(*) FROM files WHERE status='pending'")
print(f"Pending now: {c.fetchone()[0]}")

c.execute("SELECT COUNT(*) FROM files WHERE status='indexed'")
print(f"Indexed: {c.fetchone()[0]}")

conn.commit()
conn.close()
