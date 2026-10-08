"""每家模型各打 E3／E5／E6 一題，印出解析結果與部分原始回應；不寫結果檔。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
run.load_env(run.DEFAULT_ENV)
jobs = {j["job"]: j for j in map(json.loads, open(os.path.join(run.HERE, "jobs.jsonl"), encoding="utf-8"))}
pick = sys.argv[2:] or ["E3|T-identity|zh_tw", "E5|Q-status|en|012", "E6|I-roc-flag|en"]
for m in sys.argv[1].split(","):
    ask = run.ASKERS[m]()
    for k in pick:
        try:
            out, tok, raw = ask(jobs[k])
            print(m, k, "=>", json.dumps(out, ensure_ascii=False)[:300], "| tok", tok)
            print("   RAW", json.dumps(raw, ensure_ascii=False)[:400])
        except Exception as e:
            print(m, k, "ERR", str(e)[:300])
