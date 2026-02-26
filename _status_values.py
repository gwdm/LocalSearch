import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

print("=== DISTINCT STATUS VALUES ===\n")
c.execute('SELECT DISTINCT status FROM files')
for row in c.fetchall():
    val = row[0]
    c2 = conn.cursor()
    c2.execute('SELECT COUNT(*) FROM files WHERE status=?', (val,))
    count = c2.fetchone()[0]
    print(f"{repr(val):20s} {count:8,d} files")

# Get sample error files without filtering
print("\n=== SAMPLE FILES (any status with 'error' in name) ===\n")
c.execute("SELECT file_path, status, error FROM files WHERE status LIKE '%error%' ORDER BY RANDOM() LIMIT 5")
for row in c.fetchall():
    print(f"Path: {row[0][:80]}")
    print(f"Status: {repr(row[1])}")
    print(f"Error: {row[2] if row[2] else '(none)'}")
    print()

conn.close()
