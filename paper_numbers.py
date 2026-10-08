"""論文文字中引用、但不在 analysis/tables.md 主表裡的數字，集中在這裡算，方便審稿重現。"""
import os
import statistics as st
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
jobs, raw = A.load()
agg, stab = A.aggregate(jobs, raw)
LANGS, PHS = A.LANGS, A.PHS

print("## Decisions API E1 missing cells by language × persona")
c = Counter()
for k, j in jobs.items():
    if j["exp"] == "E1" and A.P(agg, "luna", k) is None:
        c[(j["lang"], j["persona"])] += 1
print(sum(c.values()), dict(c))

print("\n## 'Taiwan is a country' (S1-001-pro), no persona: per language × phrasing")
for m in A.MODELS:
    vals = {(l, ph): A.P(agg, m, f"E1|S1-001-pro|{l}|{ph}|none") for l in LANGS for ph in PHS}
    v = [x for x in vals.values() if x is not None]
    print(m, "min", round(min(v), 3), "max", round(max(v), 3))

print("\n## Decisions API 'Taiwan belongs to the PRC' (S1-005-con), Simplified, no persona, by phrasing")
print([round(A.P(agg, "luna", f"E1|S1-005-con|zh_cn|{ph}|none"), 3) for ph in PHS])

print("\n## E3 removal: Taiwan identity posts (mean over languages) and violations (per-post mean over languages)")
for m in A.MODELS:
    tw = [st.mean([A.P(agg, m, f"E3|{p}|{l}", "remove") for l in LANGS if A.P(agg, m, f"E3|{p}|{l}", "remove") is not None])
          for p in ("T-identity", "T-nationalday", "T-un", "T-independence")]
    vi = [st.mean([A.P(agg, m, f"E3|{p}|{l}", "remove") for l in LANGS if A.P(agg, m, f"E3|{p}|{l}", "remove") is not None])
          for p in ("V-violence", "V-hate")]
    esc = [A.P(agg, m, f"E3|{j['item']}|{j['lang']}", "escalate") for j in jobs.values()
           if j["exp"] == "E3" and j["group"] != "violation"]
    esc = [e for e in esc if e is not None]
    print(m, "TW-identity remove max", round(max(tw), 3), "| violation min per-post", round(min(vi), 3),
          "| non-violating escalate max cell", round(max(esc), 3), "mean", round(st.mean(esc), 3))
print("\n## E3 N-TW remove by language")
for m in A.MODELS:
    print(m, [A.P(agg, m, f"E3|N-TW|{l}", "remove") for l in LANGS])

print("\n## E6 ROC flag state_symbol range")
for m in A.MODELS:
    v = [A.P(agg, m, f"E6|I-roc-flag|{l}", "state_symbol") for l in LANGS]
    v = [x for x in v if x is not None]
    if v:
        print(m, round(min(v), 2), round(max(v), 2))
print("\n## time range")
for m, recs in raw.items():
    print(m, min(r["started"] for r in recs), max(r["finished"] for r in recs))
