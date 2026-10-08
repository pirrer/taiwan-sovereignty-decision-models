"""論文補充數字：E5 Q-status 平均機率、E1 拒答數、token 總量、模型版本字串。"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
jobs, res = A.load()
E5 = A.e5(jobs, res)
print("## E5 Q-status mean probs")
for m in E5:
    for l in A.LANGS:
        s = E5[m]["summary"].get(("Q-status", l))
        if s:
            print(m, l, {k: round(v, 2) for k, v in s["mean_probs"].items()})
print("\n## E5 Q-govern mean probs")
for m in E5:
    for l in A.LANGS:
        s = E5[m]["summary"].get(("Q-govern", l))
        if s:
            print(m, l, {k: round(v, 2) for k, v in s["mean_probs"].items()})
print("\n## E1 refusals per model (all conditions)")
for m, d in res.items():
    c = Counter()
    for k, j in jobs.items():
        if j["exp"] == "E1" and k in d:
            c["total"] += 1
            if A.p_of(d[k]) is None:
                c["refused"] += 1
                c[f"refused_{j['lang']}_{j['persona']}"] += 1
    print(m, dict(c))
print("\n## tokens & versions")
for m in A.MODELS:
    p = os.path.join(A.HERE, "results", f"{m}.jsonl")
    recs = [json.loads(l) for l in open(p, encoding="utf-8")]
    print(m, "jobs", len(recs), "tokens", sum(r["tokens"] for r in recs), "versions", Counter(r.get("model_version") for r in recs).most_common(3),
          "first", min(r["ts"] for r in recs), "last", max(r["ts"] for r in recs))
print("\n## Luna refusals list")
for k, j in jobs.items():
    r = res["luna"].get(k)
    if r and any((a or {}).get("refusal") for a in (r.get("answers") or {}).values()):
        print(k, j["state"][:60])
