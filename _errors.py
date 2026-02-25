import sqlite3
conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()
c.execute("SELECT error, COUNT(*) as cnt FROM files WHERE status='error' GROUP BY error ORDER BY cnt DESC LIMIT 10")
for row in c.fetchall():
    print(f"{row[1]:>6}  {row[0][:150]}")
conn.close()
