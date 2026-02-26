import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get sample of "other" errors (not OneDrive or audio transcription)
print("=== OTHER ERROR SAMPLES (not OneDrive or audio transcription) ===\n")
c.execute("""
    SELECT file_path, error 
    FROM files 
    WHERE status=? 
      AND error NOT LIKE '%No such file%' 
      AND error NOT LIKE '%no such file%'
      AND error NOT LIKE '%Failed to transcribe audio%'
    LIMIT 10
""", ('error',))

for i, (path, err) in enumerate(c.fetchall(), 1):
    print(f"Sample {i}:")
    print(f"File: {path}")
    print(f"Error: {err}")
    print("-" * 80)

conn.close()
