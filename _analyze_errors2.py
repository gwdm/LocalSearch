import sqlite3, re
from collections import Counter

conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()
c.execute("SELECT error, file_path FROM files WHERE status='error'")
rows = c.fetchall()
conn.close()

print(f"Total errors: {len(rows)}\n")

# Classify errors into categories
categories = Counter()
samples = {}

for err, path in rows:
    if not err:
        cat = "NULL/empty error"
    elif "Unknown code page" in err:
        cat = "Unknown code page (corrupt .msg encoding)"
    elif "has no attribute" in err:
        cat = "Module attribute error"
    elif "Failed to open MSG" in err:
        # extract the reason after the filename
        m = re.search(r'\.msg:\s*(.+)', err)
        reason = m.group(1).strip() if m else "unknown reason"
        cat = f"Failed to open MSG: {reason}"
    elif "No text extracted" in err:
        cat = "No text extracted (empty file)"
    elif "not installed" in err:
        cat = "Missing dependency"
    elif "timeout" in err.lower() or "timed out" in err.lower():
        cat = "Extraction timeout"
    elif "Permission" in err or "Access" in err:
        cat = "Permission/access denied"
    elif "corrupt" in err.lower() or "invalid" in err.lower():
        cat = "Corrupt/invalid file"
    elif "memory" in err.lower() or "MemoryError" in err:
        cat = "Memory error"
    elif "UnicodeDecodeError" in err or "codec" in err:
        cat = "Unicode/encoding error"
    elif "PDF" in err or "pdf" in err:
        cat = "PDF extraction error"
    else:
        # Use first 80 chars as category
        cat = err[:80]
    
    categories[cat] += 1
    if cat not in samples:
        samples[cat] = []
    if len(samples[cat]) < 3:
        samples[cat].append((path, err[:150]))

print(f"{'#':>2}  {'Count':>5}  {'%':>5}  Category")
print("-" * 80)
for i, (cat, cnt) in enumerate(categories.most_common(10), 1):
    pct = cnt / len(rows) * 100
    print(f"{i:>2}  {cnt:>5}  {pct:>5.1f}  {cat}")
    for path, err in samples[cat]:
        ext = path.rsplit('.', 1)[-1] if '.' in path else '?'
        print(f"              .{ext}  {path[-80:]}")
    print()
