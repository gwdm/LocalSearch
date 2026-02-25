import sqlite3

conn = sqlite3.connect("data/localsearch_meta.db")
c = conn.cursor()
c.execute("SELECT file_path FROM files WHERE status='error' AND error LIKE '%code page 4093%' LIMIT 10")
paths = [r[0] for r in c.fetchall()]
conn.close()

from localsearch.extractors.msg import MsgExtractor
from localsearch.extractors.text import TextExtractor
from localsearch.extractors.pdf import PDFExtractor
from localsearch.extractors.docx import DocxExtractor
from localsearch.extractors.image import ImageExtractor

ext = MsgExtractor(extractors={
    "text": TextExtractor(),
    "pdf": PDFExtractor(),
    "docx": DocxExtractor(),
    "image": ImageExtractor(),
})

ok = 0
fail = 0
for p in paths:
    try:
        r = ext.extract(p)
        ok += 1
        print(f"OK  {len(r.text):>6} chars  {p[-70:]}")
    except Exception as e:
        fail += 1
        print(f"ERR {str(e)[:80]}  {p[-70:]}")

print(f"\n{ok}/{ok+fail} succeeded")
