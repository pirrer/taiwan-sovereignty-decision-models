"""印出 results/*.jsonl 的解析結果摘要（除錯用）。用法: python peek.py [筆數上限]"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
for p in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "*.jsonl"))):
    for i, l in enumerate(open(p, encoding="utf-8")):
        if i >= limit:
            break
        r = json.loads(l)
        a = {k: {kk: vv for kk, vv in v.items() if kk != "text"} for k, v in (r["answers"] or {}).items()}
        print(os.path.basename(p), r["job"], r.get("model_version"), json.dumps(a, ensure_ascii=False)[:260], "calls", r["http_calls"])
