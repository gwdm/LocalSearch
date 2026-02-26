import sqlite3
import re
from collections import Counter

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get all errors using parameterized query
c.execute('SELECT error FROM files WHERE status=?', ('error',))
errors = [row[0] for row in c.fetchall() if row[0]]

print(f"=== ANALYZING {len(errors):,} ERRORS ===\n")

# Categorize errors
categories = Counter()

for err in errors:
    if "No such file" in err or "no such file" in err:
        categories["OneDrive Files-On-Demand (file not downloaded)"] += 1
    elif "Cannot read file" in err or "FileNotFoundError" in err:
        categories["File not found / access error"] += 1
    elif "ffmpeg failed" in err:
        categories["FFmpeg audio extraction failed"] += 1
    elif "timed out" in err.lower():
        categories["Extraction timeout"] += 1
    elif "extract_msg" in err or "MSG" in err:
        categories["MSG/Outlook extraction failed"] += 1
    elif "PDF" in err or "PyMuPDF" in err:
        categories["PDF extraction failed"] += 1
    elif "OCR" in err or "tesseract" in err:
        categories["Image OCR failed"] += 1
    elif "permission" in err.lower() or "access denied" in err.lower():
        categories["Permission denied"] += 1
    elif "encoding" in err.lower() or "decode" in err.lower():
        categories["Text encoding error"] += 1
    elif "corrupt" in err.lower() or "invalid" in err.lower():
        categories["Corrupted/invalid file"] += 1
    else:
        # Try to extract first few words
        first_words = ' '.join(err.split()[:6])
        categories[f"Other: {first_words}..."] += 1

# Sort by frequency
print("TOP ERROR CATEGORIES:\n")
for i, (cat, count) in enumerate(categories.most_common(10), 1):
    pct = (count / len(errors)) * 100
    print(f"{i}. {cat}")
    print(f"   Count: {count:,} ({pct:.1f}%)\n")

print("=" * 80)
print(f"TOTAL ERRORS: {len(errors):,}")
print("=" * 80)

# Show sample errors for top 3 categories
print("\n=== SAMPLE ERRORS (Top 3 Categories) ===\n")
for i, (cat, _) in enumerate(categories.most_common(3), 1):
    print(f"\n{i}. {cat}:")
    print("-" * 60)
    
    # Find first error matching this category
    for err in errors:
        matches = False
        if cat.startswith("OneDrive") and ("No such file" in err or "no such file" in err):
            matches = True
        elif cat.startswith("File not found") and ("Cannot read file" in err or "FileNotFoundError" in err):
            matches = True
        elif cat.startswith("FFmpeg") and "ffmpeg failed" in err:
            matches = True
        elif cat.startswith("Extraction timeout") and "timed out" in err.lower():
            matches = True
        elif cat.startswith("MSG") and ("extract_msg" in err or "MSG" in err):
            matches = True
        elif cat.startswith("PDF") and ("PDF" in err or "PyMuPDF" in err):
            matches = True
        elif cat.startswith("Image OCR") and ("OCR" in err or "tesseract" in err):
            matches = True
        
        if matches:
            print(f"   {err[:200]}")
            break

conn.close()
