"""Check what error types remain in database."""
import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get top error messages
c.execute("""
    SELECT error, COUNT(*) as cnt
    FROM files 
    WHERE status='error'
    GROUP BY error
    ORDER BY cnt DESC
    LIMIT 20
""")

print("Remaining errors (top 20 types):")
total = 0
for error, count in c.fetchall():
    print(f"  [{count:,}] {error[:100] if error else '(NULL error message)'}")
    total += count

print(f"\nTotal errors shown: {total:,}")

# Get overall count
c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
print(f"Total in database: {c.fetchone()[0]:,}")

conn.close()
