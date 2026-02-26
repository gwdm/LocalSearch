import sqlite3
import re

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

# Get all errors
c.execute('SELECT error FROM files WHERE status="error"')
errors = [row[0] for row in c.fetchall()]

print(f"=== ANALYZING {len(errors):,} ERRORS ===\n")

# Categorize errors
categories = {}

for err in errors:
    if not err:
        category = "Empty/NULL error message"
    elif "ffmpeg failed" in err:
        category = "FFmpeg audio extraction failed"
    elif "Cannot read file" in err or "No such file" in err:
        category = "File not found / access error"
    elif "timed out" in err.lower():
        category = "Extraction timeout"
    elif "extract_msg" in err or "MSG" in err:
        category = "MSG/Outlook extraction failed"
    elif "PDF" in err or "PyMuPDF" in err:
        category = "PDF extraction failed"
    elif "OCR" in err or "tesseract" in err:
        category = "Image OCR failed"
    elif "permission" in err.lower() or "access denied" in err.lower():
        category = "Permission denied"
    elif "encoding" in err.lower() or "decode" in err.lower():
        category = "Text encoding error"
    elif "corrupt" in err.lower() or "invalid" in err.lower():
        category = "Corrupted/invalid file"
    else:
        # Try to extract first few words
        first_words = ' '.join(err.split()[:5])
        category = f"Other: {first_words}..."
    
    categories[category] = categories.get(category, 0) + 1

# Sort by frequency
sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)

print("TOP ERROR CATEGORIES:\n")
for i, (cat, count) in enumerate(sorted_cats[:10], 1):
    pct = (count / len(errors)) * 100
    print(f"{i}. {count:6,d} ({pct:5.1f}%) | {cat}")

print(f"\n{'='*80}")
print(f"TOTAL ERRORS: {len(errors):,}")

# Overall status
print(f"\n{'='*80}")
print("=== FILE STATUS SUMMARY ===\n")
c.execute('SELECT status, COUNT(*) FROM files GROUP BY status ORDER BY COUNT(*) DESC')
for row in c.fetchall():
    print(f"{row[0]:12s} {row[1]:8,d}")

# Sample errors from top 3 categories
print(f"\n{'='*80}")
print("=== SAMPLE ERRORS (Top 3 Categories) ===\n")

for i, (cat, count) in enumerate(sorted_cats[:3], 1):
    print(f"\n{i}. {cat} ({count:,} occurrences)")
    print("   Sample:")
    # Find first error matching this category
    for err in errors:
        matches = False
        if cat == "FFmpeg audio extraction failed" and "ffmpeg failed" in err:
            matches = True
        elif cat == "File not found / access error" and ("Cannot read file" in err or "No such file" in err):
            matches = True
        elif "Other:" in cat and err.startswith(cat.replace("Other: ", "").replace("...", "")):
            matches = True
        
        if matches:
            print(f"   {err[:200]}")
            if len(err) > 200:
                print("   ...")
            break

conn.close()
