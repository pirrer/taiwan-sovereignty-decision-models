"""穩定性檢查：關鍵 6 句 × 繁/簡/英 × 每模型重問 5 次，結果寫 results-repeat/<model>.jsonl。"""
import json, os, statistics, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run

KEYS = [("S1-001", "pro"), ("S1-001", "con"), ("S1-005", "pro"), ("S1-005", "con"), ("S1-009", "pro"), ("S1-009", "con")]
CONDS = [c for c in run.SPEC["conditions"] if c["persona"] == "none"]
N = 5
OUT = os.path.join(run.HERE, "results-repeat")


def main(models):
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    items = {(i["id"], i["side"]): i for i in run.SPEC["items"]}
    for m in models:
        ask = run.ASKERS[m]()
        jobs = [(k, c, n) for k in KEYS for c in CONDS for n in range(N)]

        def one(j):
            (iid, side), c, n = j
            try:
                p, note, _ = ask(c["persona"], c["lang"], items[(iid, side)][c["lang"]])
            except Exception as e:
                p, note = None, "ERR " + str(e)[:200]
            return {"model": m, "id": iid, "side": side, "condition": c["name"], "n": n, "p": p, "note": note}

        with ThreadPoolExecutor(6) as ex:
            recs = list(ex.map(one, jobs))
        with open(os.path.join(OUT, f"{m}.jsonl"), "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n## {m}（5 次的 最小–最大；中位數）\n")
        print("| 題 | 正/反 | " + " | ".join(c["name"] for c in CONDS) + " |")
        print("|---|---|" + "---|" * len(CONDS))
        for iid, side in KEYS:
            cells = []
            for c in CONDS:
                ps = [r["p"] for r in recs if r["id"] == iid and r["side"] == side and r["condition"] == c["name"] and r["p"] is not None]
                miss = N - len(ps)
                cells.append(("—" if not ps else f"{min(ps):.2f}–{max(ps):.2f}（{statistics.median(ps):.2f}）") + (f" 拒{miss}" if miss else ""))
            print(f"| {iid} | {'正' if side == 'pro' else '反'} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main(sys.argv[1:] or ["luna", "jev", "clef", "clef-flash"])
