"""Reset error status for files that can now be processed successfully."""
import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Count errors by category
c.execute("""
    SELECT 
        CASE 
            WHEN error LIKE '%No such file%' OR error LIKE '%no such file%' THEN 'onedrive'
            WHEN error LIKE '%Failed to transcribe audio%' THEN 'audio'
            ELSE 'other'
        END as category,
        COUNT(*) as count
    FROM files
    WHERE status='error'
    GROUP BY category
""")

categories = {row[0]: row[1] for row in c.fetchall()}
print("Current error breakdown:")
print(f"  OneDrive Files-On-Demand: {categories.get('onedrive', 0):,}")
print(f"  Audio transcription: {categories.get('audio', 0):,}")
print(f"  Other (mostly unrecoverable): {categories.get('other', 0):,}")
print()

# Reset OneDrive errors to pending
c.execute("""
    UPDATE files 
    SET status='pending', error=NULL
    WHERE status='error' 
      AND (error LIKE '%No such file%' OR error LIKE '%no such file%')
""")
onedrive_reset = c.rowcount

# Reset audio errors to pending
c.execute("""
    UPDATE files 
    SET status='pending', error=NULL
    WHERE status='error' 
      AND error LIKE '%Failed to transcribe audio%'
""")
audio_reset = c.rowcount

conn.commit()
conn.close()

print(f"Reset to pending:")
print(f"  OneDrive files: {onedrive_reset:,}")
print(f"  Audio files: {audio_reset:,}")
print(f"  Total: {onedrive_reset + audio_reset:,}")
print()
print("Run 'docker exec localsearch-app python -m localsearch.cli ingest' to reprocess.")
