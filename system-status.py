"""Show complete system status and recommendations."""
import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Overall stats
c.execute('SELECT COUNT(*) FROM files')
total = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM files WHERE status='indexed'")
indexed = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM files WHERE status='error'")
errors = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM files WHERE status='pending'")
pending = c.fetchone()[0]

print("=" * 80)
print("LOCALSEARCH SYSTEM STATUS")
print("=" * 80)
print(f"Total files tracked: {total:,}")
print(f"Successfully indexed: {indexed:,} ({indexed/total*100:.1f}%)")
print(f"Pending processing: {pending:,} ({pending/total*100:.1f}%)")
print(f"Errors: {errors:,} ({errors/total*100:.1f}%)")
print()

# Error breakdown
c.execute("""
    SELECT 
        CASE 
            WHEN error LIKE '%No such file%' OR error LIKE '%no such file%' THEN 'OneDrive Files-On-Demand'
            WHEN error LIKE '%Failed to transcribe audio%' THEN 'Audio transcription (FIXED)'
            WHEN error LIKE '%extract MSG%' THEN 'MSG extraction (unrecoverable)'
            ELSE 'Other'
        END as category,
        COUNT(*) as count
    FROM files
    WHERE status=?
    GROUP BY category
    ORDER BY count DESC
""", ('error',))

print("ERROR BREAKDOWN:")
print("-" * 80)
for category, count in c.fetchall():
    pct = (count / errors) * 100
    recoverable = "✓ RECOVERABLE" if "FIXED" in category or "OneDrive" in category else "✗ Unrecoverable"
    print(f"{category:40s}: {count:6,} ({pct:5.1f}%) {recoverable}")

print()
print("=" * 80)
print("RECOMMENDED ACTIONS:")
print("=" * 80)
print()
print("1. Download OneDrive Files (59,704 errors)")
print("   Run: .\\download-onedrive-files.ps1")
print()
print("2. Reset recoverable errors to pending (91,665 errors)")
print("   Run: python reset-recoverable-errors.py")
print()
print("3. Reprocess pending files in Docker")
print("   Run: docker exec localsearch-app python -m localsearch.cli ingest")
print()
print("Expected outcome:")
print(f"  - Success rate: {(indexed + 91665) / total * 100:.1f}%")
print(f"  - Remaining errors: {errors - 91665:,} (unrecoverable)")

conn.close()
