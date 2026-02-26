import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get one of the "other" errors to see the full message
c.execute("""
    SELECT file_path, error 
    FROM files 
    WHERE status='error' AND file_path LIKE '%2021-10-24 093145-R-.msg'
""")

result = c.fetchone()
if result:
    print(f"File: {result[0]}")
    print(f"\nFull error message:")
    print(result[1])
else:
    print("File not found")

conn.close()
