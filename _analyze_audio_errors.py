import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get sample of audio transcription errors
print("=== AUDIO TRANSCRIPTION ERROR SAMPLES ===\n")
c.execute("""
    SELECT file_path, error 
    FROM files 
    WHERE status=? AND error LIKE '%Failed to transcribe audio%'
    LIMIT 5
""", ('error',))

for i, (path, err) in enumerate(c.fetchall(), 1):
    print(f"Sample {i}:")
    print(f"File: {path}")
    print(f"Error: {err}")
    print("-" * 80)

# Count audio errors vs OneDrive placeholder errors
c.execute("""
    SELECT COUNT(*) FROM files 
    WHERE status=? AND error LIKE '%Failed to transcribe audio%'
""", ('error',))
audio_count = c.fetchone()[0]

c.execute("""
    SELECT COUNT(*) FROM files 
    WHERE status=? AND (error LIKE '%No such file%' OR error LIKE '%no such file%')
""", ('error',))
onedrive_count = c.fetchone()[0]

print(f"\n=== ERROR BREAKDOWN ===")
print(f"OneDrive Files-On-Demand: {onedrive_count:,} ({onedrive_count/97395*100:.1f}%)")
print(f"Audio Transcription: {audio_count:,} ({audio_count/97395*100:.1f}%)")
print(f"Other: {97395-onedrive_count-audio_count:,} ({(97395-onedrive_count-audio_count)/97395*100:.1f}%)")

conn.close()
