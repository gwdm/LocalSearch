import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()
# Check for project files that could only be indexed by Docker
c.execute('SELECT file_path FROM files WHERE status="indexed" AND file_path LIKE "D:\\%README%" LIMIT 10')
for row in c.fetchall():
    print(row[0])
print("\n---\n")
# Also check a random sample
c.execute('SELECT file_path FROM files WHERE status="indexed" LIMIT 10 OFFSET 10000')
for row in c.fetchall():
    print(row[0])
