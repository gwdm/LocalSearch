import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Reset this specific file to pending so it gets reprocessed
test_file = r"D:\1-Msgs\London Underground.mp3"
c.execute('UPDATE files SET status=?, error=NULL WHERE file_path=?', ('pending', test_file))

# Count pending files
c.execute('SELECT COUNT(*) FROM files WHERE file_path=?', (test_file,))
print(f"File marked as pending: {c.fetchone()[0]}")

conn.commit()
conn.close()

print(f"\nTest file: {test_file}")
print("Ready to test audio transcription fix!")
