import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

print("FILES table schema:")
c.execute('PRAGMA table_info(files)')
for row in c.fetchall():
    print(f"  {row[1]:20s} {row[2]}")

print("\nFirst error record:")
c.execute('SELECT * FROM files WHERE status="error" LIMIT 1')
cols = [desc[0] for desc in c.description]
row = c.fetchone()
if row:
    for col, val in zip(cols, row):
        print(f"  {col:20s} {str(val)[:100]}")

conn.close()
