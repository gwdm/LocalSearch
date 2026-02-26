import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Check error files
c.execute('SELECT COUNT(*) FROM files WHERE status="error"')
error_count = c.fetchone()[0]

c.execute('SELECT COUNT(*) FROM files WHERE status="error" AND error IS NOT NULL')
error_with_msg = c.fetchone()[0]

c.execute('SELECT COUNT(*) FROM files WHERE status="error" AND (error IS NULL OR error="")')
error_without_msg = c.fetchone()[0]

print(f"=== ERROR ANALYSIS ===\n")
print(f"Total error files: {error_count:,}")
print(f"  With error message: {error_with_msg:,}")
print(f"  Without error message: {error_without_msg:,}")

# Sample some error records
print(f"\n=== SAMPLE ERROR RECORDS ===\n")
c.execute('SELECT file_path, status, error FROM files WHERE status="error" LIMIT 10')
for i, row in enumerate(c.fetchall(), 1):
    path, status, err = row
    # Show just filename
    filename = path.split('\\')[-1] if '\\' in path else path
    print(f"{i}. {filename[:60]}")
    print(f"   Error: {err if err else '(NULL/empty)'}")

# Check what's in the error column for any file
print(f"\n=== ALL STATUS TYPES ===\n")
c.execute('SELECT status, COUNT(*) FROM files GROUP BY status ORDER BY COUNT(*) DESC')
for row in c.fetchall():
    print(f"{row[0]:12s} {row[1]:8,d}")

conn.close()
