import sqlite3
import os
import sys
sys.path.insert(0, '.')

from localsearch.extractors.msg import MsgExtractor

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get 10 MSG files with errors
c.execute("""
    SELECT file_path, error 
    FROM files 
    WHERE status='error' AND error LIKE '%extract MSG file%'
    LIMIT 10
""")

extractor = MsgExtractor()

print("Testing 10 failing MSG files...")
print("=" * 80)

results = {
    "corrupted_ole": [],
    "no_streams": [],
    "encoding_error": [],
    "other": []
}

for file_path, db_error in c.fetchall():
    if not os.path.exists(file_path):
        print(f"SKIP (not found): {os.path.basename(file_path)}")
        continue
        
    print(f"\nTesting: {os.path.basename(file_path)}")
    
    # Try extract_msg
    try:
        import extract_msg
        msg = extract_msg.Message(file_path)
        print(f"  extract_msg: SUCCESS")
        msg.close()
    except Exception as e:
        error_str = str(e).lower()
        if "ole fat" in error_str or "sector index" in error_str:
            results["corrupted_ole"].append(file_path)
            print(f"  extract_msg: FAILED (corrupted OLE structure)")
        elif "encoding" in error_str or "decode" in error_str:
            results["encoding_error"].append(file_path)
            print(f"  extract_msg: FAILED (encoding error)")
        else:
            results["other"].append(file_path)
            print(f"  extract_msg: FAILED ({str(e)[:60]})")
    
    # Try olefile
    try:
        import olefile
        ole = olefile.OleFileIO(file_path)
        streams = list(ole.listdir())
        if not streams:
            results["no_streams"].append(file_path)
            print(f"  olefile: Opened but no streams found")
        else:
            print(f"  olefile: SUCCESS ({len(streams)} streams)")
        ole.close()
    except Exception as e:
        print(f"  olefile: FAILED ({str(e)[:60]})")

print("\n" + "=" * 80)
print("SUMMARY:")
print(f"Corrupted OLE structure: {len(results['corrupted_ole'])}")
print(f"No streams (empty file): {len(results['no_streams'])}")
print(f"Encoding errors: {len(results['encoding_error'])}")
print(f"Other errors: {len(results['other'])}")

conn.close()
