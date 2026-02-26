import sqlite3
import os
import sys
sys.path.insert(0, '.')

from localsearch.extractors.msg import MsgExtractor

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get all MSG files with errors
c.execute("""
    SELECT file_path 
    FROM files 
    WHERE status='error' AND error LIKE '%extract MSG file%'
""")

all_files = [row[0] for row in c.fetchall()]
print(f"Total MSG errors in database: {len(all_files)}")

# Sample 50 files to test
import random
random.seed(42)
sample_files = random.sample(all_files, min(50, len(all_files)))

extractor = MsgExtractor()

results = {
    "actually_works": 0,
    "corrupted_ole": 0,
    "not_found": 0,
    "empty_properties": 0,
    "not_ole_file": 0,
    "other": 0
}

print(f"\nTesting sample of {len(sample_files)} files...")
print("=" * 80)

for i, file_path in enumerate(sample_files, 1):
    if i % 10 == 0:
        print(f"Progress: {i}/{len(sample_files)}")
    
    if not os.path.exists(file_path):
        results["not_found"] += 1
        continue
    
    try:
        result = extractor.extract(file_path)
        results["actually_works"] += 1
    except Exception as e:
        error_str = str(e).lower()
        if "ole fat" in error_str or "sector index" in error_str:
            results["corrupted_ole"] += 1
        elif "not an ole2" in error_str or "not a microsoft ole2" in error_str:
            results["not_ole_file"] += 1
        else:
            # Check if it's an empty properties file
            try:
                import olefile
                ole = olefile.OleFileIO(file_path)
                streams = list(ole.listdir())
                if len(streams) <= 1 and ole.exists("__properties_version1.0"):
                    # Check if properties stream is empty
                    stream = ole.openstream("__properties_version1.0")
                    if len(stream.read()) == 0:
                        results["empty_properties"] += 1
                    else:
                        results["other"] += 1
                        print(f"OTHER: {os.path.basename(file_path)} - {str(e)[:60]}")
                else:
                    results["other"] += 1
                    print(f"OTHER: {os.path.basename(file_path)} - {str(e)[:60]}")
                ole.close()
            except:
                results["other"] += 1
                print(f"OTHER: {os.path.basename(file_path)} - {str(e)[:60]}")

print("\n" + "=" * 80)
print("SAMPLE RESULTS:")
for category, count in results.items():
    pct = (count / len(sample_files)) * 100
    print(f"{category:25s}: {count:3d} ({pct:5.1f}%)")

print("\n" + "=" * 80)
print("EXTRAPOLATED TO ALL 5,730 MSG ERRORS:")
total = len(all_files)
for category, count in results.items():
    extrapolated = int((count / len(sample_files)) * total)
    print(f"{category:25s}: ~{extrapolated:,d}")

conn.close()
