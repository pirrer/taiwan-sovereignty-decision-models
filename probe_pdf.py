"""抓 PDF 並搜尋字串（查核官方原始文件用）。用法: python probe_pdf.py <url> <pattern>..."""
import io
import re
import sys
import urllib.request

from pypdf import PdfReader

sys.stdout.reconfigure(encoding="utf-8")
url, pats = sys.argv[1], sys.argv[2:]
try:
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
    text = " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    text = re.sub(r"\s+", " ", text)
    for p in pats:
        m = re.search(p, text)
        print("FOUND" if m else "NO", "|", p, "|", text[max(0, m.start() - 80): m.end() + 80] if m else "")
except Exception as e:
    print("ERROR", e)
