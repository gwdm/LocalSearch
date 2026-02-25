import sqlite3

conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()
c.execute("SELECT file_path FROM files WHERE status='error' AND error LIKE '%code page 4093%' LIMIT 5")
paths = [r[0] for r in c.fetchall()]
conn.close()

import extract_msg

for p in paths:
    print(f"\n--- {p[-70:]} ---")

    # Try with overrideEncoding='utf-8'
    for enc in ['utf-8', 'latin-1', 'cp1252', 'chardet']:
        try:
            msg = extract_msg.Message(p, overrideEncoding=enc)
            subj = (msg.subject or "")[:60]
            body_len = len(msg.body or "")
            msg.close()
            print(f"  {enc:>8}: OK  subj={subj!r}  body={body_len} chars")
            break
        except Exception as e:
            err = str(e)[:80]
            print(f"  {enc:>8}: FAIL  {err}")
