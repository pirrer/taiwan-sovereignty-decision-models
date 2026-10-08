"""
台灣主權陳述 × 決策模型測試（2026-10-08）。

每句陳述問「是否正確」，取模型給的成立機率 P（0–1）。28 句 × 5 條件（statements.json）。
已跑過的（model, id, side, condition）會略過，結果累加在 results/<model>.jsonl。

模型：
    clef-flash / clef  Cloudflare Workers AI（金鑰在 %APPDATA%/cloudflare-ai/，選題板同一組）
    haiku              Claude Haiku 5.5，走 OpenRouter（.env 的 OPENROUTER_API_KEY）；通用模型，P 是它自報的數字
    luna               OpenAI Decisions API，gpt-6-luna（需 OPENAI_API_KEY；OpenRouter 沒有代理這個端點）
    jev                TypeSafe Jev（有 TYPESAFE_API_KEY 走官方免費額度，否則走 OpenRouter；jev-latest；Clef 與 Jev API 相容，送同一種 body）

用法:
    python run.py clef-flash haiku
    python run.py --summary
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
OUT = os.path.join(HERE, "results")
SPEC = json.load(open(os.path.join(HERE, "statements.json"), encoding="utf-8"))

# 金鑰放在本資料夾的 .env（已 gitignore）：OPENROUTER_API_KEY、OPENAI_API_KEY、TYPESAFE_API_KEY
if os.path.exists(os.path.join(ROOT, ".env")):
    for _line in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig"):
        _k, _, _v = _line.strip().partition("=")
        if _k and _v and not _k.startswith("#"):
            os.environ.setdefault(_k, _v.strip().strip('"'))

ASK_NUMBER = {
    "zh_tw": "請只回覆一個 0 到 1 之間的數字，代表這句陳述正確的機率，不要加任何文字。",
    "zh_cn": "请只回复一个 0 到 1 之间的数字，代表这句陈述正确的概率，不要加任何文字。",
    "en": "Reply with only a number between 0 and 1: the probability that this statement is true. No other text.",
}


def post(url, body, headers, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError) as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last)


def state_text(persona, statement):
    p = SPEC["personas"][persona]
    return f"{p}\n\n{statement}" if p else statement


def decision_body(model, persona, lang, statement):
    return {"model": model, "state": state_text(persona, statement),
            "questions": {"true": {"type": "noul", "instructions": SPEC["instructions"][lang]}}}


def parse_decision(res):
    a = res["answers"]["true"]
    if "noul" in a:
        return float(a["noul"]), None
    return None, json.dumps(a, ensure_ascii=False)[:200]


def ask_clef(model):
    cfg = os.path.join(os.environ.get("APPDATA", ""), "cloudflare-ai")
    token = open(os.path.join(cfg, "token.txt"), encoding="utf-8-sig").read().split()[0]
    acct = open(os.path.join(cfg, "account_id.txt"), encoding="utf-8-sig").read().strip()

    def f(persona, lang, statement):
        res = post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/cloudflare/{model}",
                   decision_body(model, persona, lang, statement), {"Authorization": f"Bearer {token}"})["result"]
        p, note = parse_decision(res)
        return p, note, res.get("usage", {}).get("input_tokens", 0)
    return f


def openrouter_key():
    return os.environ["OPENROUTER_API_KEY"]


def ask_jev():
    # 優先用 TypeSafe 自己的金鑰（用戶有免費額度），沒有才走 OpenRouter 計費
    if os.environ.get("TYPESAFE_API_KEY"):
        url, key = "https://api.typesafe.ai/v1/systemone", os.environ["TYPESAFE_API_KEY"]
    else:
        url, key = "https://openrouter.ai/api/v1/systemone", openrouter_key()

    def f(persona, lang, statement):
        res = post(url, decision_body("jev-latest", persona, lang, statement), {"Authorization": f"Bearer {key}"})
        p, note = parse_decision(res)
        return p, note, res.get("usage", {}).get("input_tokens", 0)
    return f


def ask_luna():
    key = os.environ["OPENAI_API_KEY"]

    def f(persona, lang, statement):
        res = post("https://api.openai.com/v1/decisions", {
            "model": "gpt-6-luna", "input": state_text(persona, statement),
            "questions": [{"type": "predicate", "name": "true", "instructions": SPEC["instructions"][lang]}],
        }, {"Authorization": f"Bearer {key}"})
        a = res["answers"][0]
        if a.get("type") == "refusal":
            return None, "refusal", res.get("usage", {}).get("input_tokens", 0)
        p = a.get("probability", a.get("value"))
        return (float(p) if p is not None else None), (None if p is not None else json.dumps(a)[:200]), \
            res.get("usage", {}).get("input_tokens", 0)
    return f


def ask_haiku():
    key = openrouter_key()

    def f(persona, lang, statement):
        msgs = []
        if SPEC["personas"][persona]:
            msgs.append({"role": "system", "content": SPEC["personas"][persona]})
        msgs.append({"role": "user", "content": f"{statement}\n\n{SPEC['instructions'][lang]}{ASK_NUMBER[lang]}"})
        res = post("https://openrouter.ai/api/v1/chat/completions",
                   {"model": "anthropic/claude-haiku-5.5", "messages": msgs, "temperature": 0, "max_tokens": 300,
                    # 關掉思考：決策模型不推理，對照組也直接給數字；不關的話 200 token 全耗在思考、content 是空的
                    "reasoning": {"enabled": False}},
                   {"Authorization": f"Bearer {key}"})
        text = (res["choices"][0]["message"].get("content") or "").strip()
        m = re.fullmatch(r"\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*", text)
        return (float(m.group(1)) if m else None), (None if m else text[:300]), \
            res.get("usage", {}).get("prompt_tokens", 0)
    return f


ASKERS = {"clef-flash": lambda: ask_clef("clef-flash"), "clef": lambda: ask_clef("clef"),
          "haiku": ask_haiku, "luna": ask_luna, "jev": ask_jev}


def load(model):
    path = os.path.join(OUT, f"{model}.jsonl")
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def run(model):
    ask = ASKERS[model]()
    done = {(r["id"], r["side"], r["condition"]) for r in load(model) if r.get("error") is None}
    jobs = [(it, c) for c in SPEC["conditions"] for it in SPEC["items"]
            if (it["id"], it["side"], c["name"]) not in done]

    def one(job):
        it, c = job
        rec = {"model": model, "id": it["id"], "side": it["side"], "condition": c["name"],
               "statement": it[c["lang"]], "p": None, "note": None, "tokens": 0, "error": None}
        try:
            rec["p"], rec["note"], rec["tokens"] = ask(c["persona"], c["lang"], it[c["lang"]])
        except Exception as e:
            rec["error"] = str(e)[:300]
        return rec

    os.makedirs(OUT, exist_ok=True)
    with ThreadPoolExecutor(6) as ex, open(os.path.join(OUT, f"{model}.jsonl"), "a", encoding="utf-8") as f:
        recs = list(ex.map(one, jobs))
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    errs = [r for r in recs if r["error"]]
    print(f"{model}: {len(recs)} 次呼叫，錯誤 {len(errs)}，輸入 token {sum(r['tokens'] for r in recs)}")
    for r in errs[:3]:
        print("  ", r["error"])


def summary():
    sys.stdout.reconfigure(encoding="utf-8")
    conds = [c["name"] for c in SPEC["conditions"]]
    for fn in sorted(os.listdir(OUT)):
        model = fn[:-6]
        rows = {}
        for r in load(model):
            if r.get("error") is None:
                rows[(r["id"], r["side"], r["condition"])] = r
        print(f"\n## {model}\n")
        print("| 題 | 正/反 | " + " | ".join(conds) + " |")
        print("|---|---|" + "---|" * len(conds))
        for it in SPEC["items"]:
            cells = []
            for c in conds:
                r = rows.get((it["id"], it["side"], c))
                cells.append("—" if r is None else ("拒答/非數字" if r["p"] is None else f"{r['p']:.2f}"))
            print(f"| {it['id']} | {'正' if it['side'] == 'pro' else '反'} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    for m in a.models:
        run(m)
    if a.summary:
        summary()
