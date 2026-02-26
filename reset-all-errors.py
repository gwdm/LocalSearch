"""Reset all remaining error files to pending for retry."""
import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Count current errors
c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
error_count = c.fetchone()[0]

print(f"Current errors: {error_count:,}")
print()

# Get a sample of error types
c.execute("""
    SELECT SUBSTR(error, 1, 50), COUNT(*) as cnt
    FROM files 
    WHERE status='error'
    GROUP BY SUBSTR(error, 1, 50)
    ORDER BY cnt DESC
    LIMIT 10
""")
print("Top error type prefixes:")
for prefix, count in c.fetchall():
    print(f"  [{count}] {prefix}...")
print()

# Reset ALL errors to pending
c.execute("""
    UPDATE files 
    SET status='pending', error=NULL
    WHERE status='error'
""")
reset_count = c.rowcount

conn.commit()
conn.close()

print(f"✓ Reset {reset_count:,} files from 'error' to 'pending'")
print()
print("These files will be retried in the next ingestion pass.")
print("Run 'docker-compose restart localsearch' to restart ingestion.")
