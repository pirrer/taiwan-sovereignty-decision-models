"""analyze.aggregate 的缺漏處理單元測試：整筆遺失的重複也要在敏感度分析裡補 0.5。用法: python test_analyze.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A  # noqa: E402


def rec(job, rep, p):
    return {"job": job, "rep": rep, "answers": {"true": {"p": p} if p is not None else {"refusal": True}}}


jobs = {"J": {"job": "J", "exp": "E1", "questions": [{"name": "true", "type": "noul"}]}}
cases = {
    "all valid": ([rec("J", 0, 0.2), rec("J", 1, 0.2), rec("J", 2, 0.2)], 0.2, 0.2, 0),
    "one refusal": ([rec("J", 0, 0.2), rec("J", 1, 0.2), rec("J", 2, None)], 0.2, (0.4 + 0.5) / 3, 1),
    "one record absent": ([rec("J", 0, 0.2), rec("J", 1, 0.2)], 0.2, (0.4 + 0.5) / 3, 1),
    "all refused": ([rec("J", r, None) for r in range(3)], None, 0.5, 0),
}
ok = True
for name, (recs, p, p_imp, mixed) in cases.items():
    agg, stab = A.aggregate(jobs, {"m": recs})
    v = agg["m"]["J"]["true"]
    got = (v["p"], round(v["p_imp"], 10), stab["m"]["mixed_missing"])
    want = (p, round(p_imp, 10), mixed)
    ok &= got == want
    print("PASS" if got == want else "FAIL", name, got, want)
sys.exit(0 if ok else 1)
