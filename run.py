"""
v3 runner：jobs.jsonl 的每個 job × 重複次數，送給指定模型，結果追加到 results/<model>.jsonl；
已成功的 (job, rep) 會略過。每筆記錄保存完整原始回應（raw）、請求次數、帶時區的開始／結束時間。

模型與路線：
    luna        OpenAI Decisions API（gpt-6-luna），OPENAI_API_KEY
    jev         TypeSafe Jev（jev-latest），TYPESAFE_API_KEY；只吃文字，E6 圖片題記為 skipped、不送請求
    clef        Cloudflare Workers AI @cf/cloudflare/clef（27B）
    clef-flash  同上 @cf/cloudflare/clef-flash（9B）
    haiku       Claude Haiku 5.5 經 OpenRouter（關閉思考、temperature 0）；每個問題一次請求，P 為自報數字

選擇題：Jev／Clef 的 criteria 用不帶語意的代號當 key、選項文字當描述；OpenAI 的 choices 用代號當 value、選項文字當 description。
Haiku 選擇題：比對前把回覆與選項都轉成簡體並去標點，再比對選項文字。

用法:
    python run.py luna jev clef clef-flash haiku [--reps 3] [--exp E1,E5] [--limit N]
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import opencc

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
# 金鑰檔：環境變數 DECISION_BENCH_ENV 指定的路徑，否則用本資料夾的 .env；也可以直接設環境變數
DEFAULT_ENV = os.environ.get("DECISION_BENCH_ENV", os.path.join(HERE, ".env"))
T2S = opencc.OpenCC("t2s")


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_env(path):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            k, _, v = line.strip().partition("=")
            if k and v and not k.startswith("#"):
                os.environ.setdefault(k, v.strip().strip('"'))


class Calls:
    """記錄一個 job 實際送出的 HTTP 請求數（含重試）"""
    def __init__(self):
        self.n = 0
        self.retries = 0


def post(url, body, headers, calls, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    last = None
    for attempt in range(4):
        calls.n += 1
        if attempt:
            calls.retries += 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}"
            if e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError) as e:
            last = str(e)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(last)


def image_data_url(fname):
    mime = "image/png" if fname.endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(open(os.path.join(HERE, 'images', fname), 'rb').read()).decode()}"


def state_text(job):
    return f"{job['context']}\n\n{job['state']}" if job.get("context") else job["state"]


# ---------- System One（Jev／Clef） ----------
def s1_body(model, job):
    qs = {}
    for q in job["questions"]:
        if q["type"] == "noul":
            qs[q["name"]] = {"type": "noul", "instructions": q["instructions"]}
        else:
            qs[q["name"]] = {"type": "choice", "instructions": q["instructions"],
                             "criteria": {c["id"]: c["label"] for c in q["choices"]}}
    body = {"model": model, "state": state_text(job), "questions": qs}
    if job.get("image"):
        body["images"] = [image_data_url(job["image"])]
    return body


def s1_parse(job, res):
    ans, out = res.get("answers", {}), {}
    for q in job["questions"]:
        a = ans.get(q["name"]) or {}
        if q["type"] == "noul":
            out[q["name"]] = {"p": a.get("noul")} if a.get("noul") is not None else {"missing": True}
        else:
            by_id = {c["id"]: c["key"] for c in q["choices"]}
            probs = a.get("probabilities") or {}
            if isinstance(probs, list):
                probs = {d.get("value", d.get("label")): d.get("probability") for d in probs}
            out[q["name"]] = {"choice": by_id.get(a.get("choice")), "confidence": a.get("confidence"),
                              "probs": {by_id.get(k, k): v for k, v in probs.items()}}
    return out


def ask_clef(model):
    token, acct = os.environ.get("CLOUDFLARE_API_TOKEN"), os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not (token and acct):  # 作者本機的備援位置
        cfg = os.path.join(os.environ.get("APPDATA", ""), "cloudflare-ai")
        token = open(os.path.join(cfg, "token.txt"), encoding="utf-8-sig").read().split()[0]
        acct = open(os.path.join(cfg, "account_id.txt"), encoding="utf-8-sig").read().strip()

    def f(job, calls):
        res = post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/cloudflare/{model}",
                   s1_body(model, job), {"Authorization": f"Bearer {token}"}, calls)
        r = res["result"]
        return s1_parse(job, r), r.get("usage", {}).get("input_tokens", 0), r.get("model"), res
    return f


def ask_jev():
    key = os.environ["TYPESAFE_API_KEY"]

    def f(job, calls):
        if job.get("image"):
            return None, 0, None, {"skipped": "jev is text-only"}
        res = post("https://api.typesafe.ai/v1/systemone", s1_body("jev-latest", job), {"Authorization": f"Bearer {key}"}, calls)
        return s1_parse(job, res), res.get("usage", {}).get("input_tokens", 0), res.get("model"), res
    return f


# ---------- OpenAI Decisions ----------
def ask_luna():
    key = os.environ["OPENAI_API_KEY"]

    def f(job, calls):
        qs = []
        for q in job["questions"]:
            if q["type"] == "noul":
                qs.append({"type": "predicate", "name": q["name"], "instructions": q["instructions"]})
            else:
                qs.append({"type": "choice", "name": q["name"], "instructions": q["instructions"],
                           "choices": [{"value": c["id"], "description": c["label"]} for c in q["choices"]]})
        if job.get("image"):
            inp = [{"role": "user", "content": [{"type": "input_text", "text": state_text(job)},
                                                {"type": "input_image", "image_url": image_data_url(job["image"])}]}]
        else:
            inp = state_text(job)
        res = post("https://api.openai.com/v1/decisions", {"model": "gpt-6-luna", "input": inp, "questions": qs},
                   {"Authorization": f"Bearer {key}"}, calls)
        out = {}
        for a in res.get("answers", []):
            q = next((q for q in job["questions"] if q["name"] == a.get("name")), None)
            if q is None:
                continue
            if a.get("type") == "refusal":
                out[q["name"]] = {"refusal": True}
            elif q["type"] == "noul":
                out[q["name"]] = {"p": a.get("probability")}
            else:
                by_id = {c["id"]: c["key"] for c in q["choices"]}
                out[q["name"]] = {"choice": by_id.get(a.get("choice")), "confidence": a.get("confidence"),
                                  "probs": {by_id.get(d["value"], d["value"]): d["probability"] for d in a.get("probabilities", [])}}
        for q in job["questions"]:
            out.setdefault(q["name"], {"missing": True})
        return out, res.get("usage", {}).get("input_tokens", 0), res.get("model"), res
    return f


# ---------- Haiku ----------
ASK_NUMBER = {
    "zh_tw": "請只回覆一個 0 到 1 之間的數字，代表答案為「是」的機率，不要加任何文字。",
    "zh_cn": "请只回复一个 0 到 1 之间的数字，代表答案为“是”的概率，不要加任何文字。",
    "en": "Reply with only a number between 0 and 1: the probability that the answer is yes. No other text.",
}
ASK_CHOICE = {
    "zh_tw": "請只回覆以下其中一個選項的完整文字，不要加任何其他文字：",
    "zh_cn": "请只回复以下其中一个选项的完整文字，不要加任何其他文字：",
    "en": "Reply with only the exact text of one of the following options, nothing else:",
}


def norm(s):
    return re.sub(r"[\s\.。，,、！!「」“”\"'（）()]", "", T2S.convert(s or "")).lower()


def ask_haiku():
    key = os.environ["OPENROUTER_API_KEY"]

    def call(job, user_text, calls):
        content = [{"type": "text", "text": user_text}]
        if job.get("image"):
            content.append({"type": "image_url", "image_url": {"url": image_data_url(job["image"])}})
        msgs = ([{"role": "system", "content": job["context"]}] if job.get("context") else []) + [{"role": "user", "content": content}]
        res = post("https://openrouter.ai/api/v1/chat/completions",
                   {"model": "anthropic/claude-haiku-5.5", "messages": msgs, "temperature": 0, "max_tokens": 300,
                    "reasoning": {"enabled": False}}, {"Authorization": f"Bearer {key}"}, calls)
        return (res["choices"][0]["message"].get("content") or "").strip(), res

    POST_LABEL = {"zh_tw": "貼文：「{}」", "zh_cn": "帖文：「{}」", "en": "Post: \"{}\""}

    def f(job, calls):
        out, tokens, raws, model = {}, 0, {}, None
        lang = job["lang"]
        # E3：Haiku 不會把裸文字當成待審貼文（冒煙測試三題都回「請貼上貼文」），明確標示；決策模型的 state 本身就是輸入欄位
        state = POST_LABEL[lang].format(job["state"]) if job["exp"] == "E3" else job["state"]
        for q in job["questions"]:
            if q["type"] == "noul":
                text, res = call(job, f"{state}\n\n{q['instructions']}{ASK_NUMBER[lang]}", calls)
                m = re.fullmatch(r"\s*(0(?:\.\d+)?|1(?:\.0+)?|\.\d+)\s*", text)
                out[q["name"]] = {"p": float(m.group(1))} if m else {"refusal": True}
            else:
                opts = "\n".join(c["label"] for c in q["choices"])
                text, res = call(job, f"{job['state']}\n\n{q['instructions']}\n{ASK_CHOICE[lang]}\n{opts}", calls)
                hit = [c["key"] for c in q["choices"] if norm(c["label"]) == norm(text)]
                out[q["name"]] = {"choice": hit[0]} if len(hit) == 1 else {"refusal": True}
            out[q["name"]]["text"] = text
            tokens += res.get("usage", {}).get("prompt_tokens", 0)
            model = res.get("model")
            raws[q["name"]] = res
        return out, tokens, model, raws
    return f


ASKERS = {"luna": ask_luna, "jev": ask_jev, "haiku": ask_haiku,
          "clef": lambda: ask_clef("clef"), "clef-flash": lambda: ask_clef("clef-flash")}


def load(model):
    p = os.path.join(OUT, f"{model}.jsonl")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def run(model, exps, reps, limit):
    ask = ASKERS[model]()
    jobs = [json.loads(l) for l in open(os.path.join(HERE, "jobs.jsonl"), encoding="utf-8")]
    if exps:
        jobs = [j for j in jobs if j["exp"] in exps]
    done = {(r["job"], r["rep"]) for r in load(model) if not r.get("error")}
    todo = [(j, r) for r in range(reps) for j in jobs if (j["job"], r) not in done][: limit or None]

    def one(item):
        job, rep = item
        calls = Calls()
        rec = {"model": model, "job": job["job"], "rep": rep, "exp": job["exp"], "answers": None, "tokens": 0,
               "error": None, "started": now()}
        try:
            rec["answers"], rec["tokens"], rec["model_version"], rec["raw"] = ask(job, calls)
            if isinstance(rec["raw"], dict) and rec["raw"].get("skipped"):
                rec["skipped"] = rec["raw"]["skipped"]
        except Exception as e:
            rec["error"] = str(e)[:400]
        rec["finished"] = now()
        rec["http_calls"], rec["retries"] = calls.n, calls.retries
        return rec

    os.makedirs(OUT, exist_ok=True)
    with ThreadPoolExecutor(6) as ex, open(os.path.join(OUT, f"{model}.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        recs = []
        for r in ex.map(one, todo):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            recs.append(r)
    errs = [r for r in recs if r["error"]]
    print(f"{model}: {len(recs)} job-runs, errors {len(errs)}, http calls {sum(r['http_calls'] for r in recs)}, "
          f"retries {sum(r['retries'] for r in recs)}, input tokens {sum(r['tokens'] for r in recs)}")
    for r in errs[:3]:
        print("   ", r["job"], r["error"][:200])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--exp", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--env", default=DEFAULT_ENV)
    a = ap.parse_args()
    load_env(a.env)
    for m in a.models:
        run(m, set(filter(None, a.exp.split(","))), a.reps, a.limit)
