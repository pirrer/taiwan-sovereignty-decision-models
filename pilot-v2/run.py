"""
v2 runner：把 jobs.jsonl 的每個 job 送給指定模型，結果追加到 results/<model>.jsonl；已成功的 job 會略過。

模型與路線：
    luna        OpenAI Decisions API（gpt-6-luna），OPENAI_API_KEY
    jev         TypeSafe Jev（jev-latest），TYPESAFE_API_KEY；只吃文字，E6 圖片題略過
    clef        Cloudflare Workers AI @cf/cloudflare/clef（27B），%APPDATA%/cloudflare-ai/
    clef-flash  同上，@cf/cloudflare/clef-flash（9B）
    haiku       Claude Haiku 5.5 經 OpenRouter（關閉思考、temperature 0）；通用 LLM 對照，P 為自報數字，choice 為自選選項

金鑰從本資料夾的 .env 讀（--env 可指定）。

用法:
    python run.py luna jev clef clef-flash haiku [--exp E1,E5] [--limit 5]
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

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
DEFAULT_ENV = os.path.join(HERE, ".env")


def load_env(path):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            k, _, v = line.strip().partition("=")
            if k and v and not k.startswith("#"):
                os.environ.setdefault(k, v.strip().strip('"'))


def post(url, body, headers, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    last = None
    for attempt in range(4):
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
    path = os.path.join(HERE, "images", fname)
    mime = "image/png" if fname.endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(open(path, 'rb').read()).decode()}"


def state_text(job):
    return f"{job['context']}\n\n{job['state']}" if job.get("context") else job["state"]


# ---------- System One 系（Jev／Clef）----------
def s1_body(model, job):
    qs = {}
    for q in job["questions"]:
        if q["type"] == "noul":
            qs[q["name"]] = {"type": "noul", "instructions": q["instructions"]}
        else:  # choice：criteria 是 {選項文字: 選項文字}，依 job 給定的排列順序插入
            qs[q["name"]] = {"type": "choice", "instructions": q["instructions"],
                             "criteria": {c["value"]: c["value"] for c in q["choices"]}}
    body = {"model": model, "state": state_text(job), "questions": qs}
    if job.get("image"):
        body["images"] = [image_data_url(job["image"])]
    return body


def s1_parse(job, res):
    ans, out = res["answers"], {}
    for q in job["questions"]:
        a = ans.get(q["name"], {})
        if q["type"] == "noul":
            out[q["name"]] = {"p": a.get("noul")}
        else:
            by_value = {c["value"]: c["key"] for c in q["choices"]}
            probs = a.get("probabilities") or {}
            if isinstance(probs, list):
                probs = {d.get("value", d.get("label")): d.get("probability") for d in probs}
            out[q["name"]] = {"choice": by_value.get(a.get("choice")), "confidence": a.get("confidence"),
                              "probs": {by_value.get(k, k): v for k, v in probs.items()}}
    return out


def ask_clef(model):
    cfg = os.path.join(os.environ.get("APPDATA", ""), "cloudflare-ai")
    token = open(os.path.join(cfg, "token.txt"), encoding="utf-8-sig").read().split()[0]
    acct = open(os.path.join(cfg, "account_id.txt"), encoding="utf-8-sig").read().strip()

    def f(job):
        res = post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/cloudflare/{model}",
                   s1_body(model, job), {"Authorization": f"Bearer {token}"})["result"]
        return s1_parse(job, res), res.get("usage", {}).get("input_tokens", 0), res
    return f


def ask_jev():
    key = os.environ["TYPESAFE_API_KEY"]

    def f(job):
        if job.get("image"):
            return None, 0, {"skipped": "jev is text-only"}
        res = post("https://api.typesafe.ai/v1/systemone", s1_body("jev-latest", job), {"Authorization": f"Bearer {key}"})
        return s1_parse(job, res), res.get("usage", {}).get("input_tokens", 0), res
    return f


# ---------- OpenAI Decisions ----------
def ask_luna():
    key = os.environ["OPENAI_API_KEY"]

    def f(job):
        qs = []
        for q in job["questions"]:
            if q["type"] == "noul":
                qs.append({"type": "predicate", "name": q["name"], "instructions": q["instructions"]})
            else:
                qs.append({"type": "choice", "name": q["name"], "instructions": q["instructions"],
                           "choices": [{"value": c["value"], "description": c["value"]} for c in q["choices"]]})
        if job.get("image"):
            inp = [{"role": "user", "content": [{"type": "input_text", "text": state_text(job)},
                                                {"type": "input_image", "image_url": image_data_url(job["image"])}]}]
        else:
            inp = state_text(job)
        res = post("https://api.openai.com/v1/decisions", {"model": "gpt-6-luna", "input": inp, "questions": qs},
                   {"Authorization": f"Bearer {key}"})
        out = {}
        for a in res["answers"]:
            q = next(q for q in job["questions"] if q["name"] == a.get("name"))
            if a.get("type") == "refusal":
                out[q["name"]] = {"refusal": True}
            elif q["type"] == "noul":
                out[q["name"]] = {"p": a.get("probability")}
            else:
                by_value = {c["value"]: c["key"] for c in q["choices"]}
                out[q["name"]] = {"choice": by_value.get(a.get("choice")), "confidence": a.get("confidence"),
                                  "probs": {by_value.get(d["value"], d["value"]): d["probability"] for d in a.get("probabilities", [])}}
        return out, res.get("usage", {}).get("input_tokens", 0), res
    return f


# ---------- Haiku（通用 LLM 對照） ----------
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


def ask_haiku():
    key = os.environ["OPENROUTER_API_KEY"]

    def call(job, user_text):
        content = [{"type": "text", "text": user_text}]
        if job.get("image"):
            content.append({"type": "image_url", "image_url": {"url": image_data_url(job["image"])}})
        msgs = ([{"role": "system", "content": job["context"]}] if job.get("context") else []) + \
               [{"role": "user", "content": content}]
        res = post("https://openrouter.ai/api/v1/chat/completions",
                   {"model": "anthropic/claude-haiku-5.5", "messages": msgs, "temperature": 0, "max_tokens": 300,
                    "reasoning": {"enabled": False}}, {"Authorization": f"Bearer {key}"})
        return (res["choices"][0]["message"].get("content") or "").strip(), res.get("usage", {}).get("prompt_tokens", 0)

    def f(job):
        out, tokens, raw = {}, 0, {}
        lang = job["lang"]
        for q in job["questions"]:
            if q["type"] == "noul":
                text, n = call(job, f"{job['state']}\n\n{q['instructions']}{ASK_NUMBER[lang]}")
                m = re.fullmatch(r"\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*", text)
                out[q["name"]] = {"p": float(m.group(1))} if m else {"refusal": True, "text": text[:300]}
            else:
                opts = "\n".join(c["value"] for c in q["choices"])
                text, n = call(job, f"{job['state']}\n\n{q['instructions']}\n{ASK_CHOICE[lang]}\n{opts}")
                hit = [c["key"] for c in q["choices"] if c["value"].strip() == text.strip().strip("。.")]
                out[q["name"]] = {"choice": hit[0]} if hit else {"refusal": True, "text": text[:300]}
            tokens += n
            raw[q["name"]] = text
        return out, tokens, raw
    return f


ASKERS = {"luna": ask_luna, "jev": ask_jev, "haiku": ask_haiku,
          "clef": lambda: ask_clef("clef"), "clef-flash": lambda: ask_clef("clef-flash")}


def load(model):
    p = os.path.join(OUT, f"{model}.jsonl")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def run(model, exps, limit):
    ask = ASKERS[model]()
    jobs = [json.loads(l) for l in open(os.path.join(HERE, "jobs.jsonl"), encoding="utf-8")]
    if exps:
        jobs = [j for j in jobs if j["exp"] in exps]
    done = {r["job"] for r in load(model) if not r.get("error")}
    todo = [j for j in jobs if j["job"] not in done][: limit or None]

    def one(job):
        rec = {"model": model, "job": job["job"], "exp": job["exp"], "answers": None, "tokens": 0, "error": None,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            rec["answers"], rec["tokens"], raw = ask(job)
            rec["model_version"] = raw.get("model") if isinstance(raw, dict) else None
            if isinstance(raw, dict) and raw.get("skipped"):
                rec["skipped"] = raw["skipped"]
        except Exception as e:
            rec["error"] = str(e)[:400]
        return rec

    os.makedirs(OUT, exist_ok=True)
    with ThreadPoolExecutor(6) as ex, open(os.path.join(OUT, f"{model}.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        recs = []
        for r in ex.map(one, todo):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            recs.append(r)
    errs = [r for r in recs if r["error"]]
    print(f"{model}: {len(recs)} jobs, errors {len(errs)}, input tokens {sum(r['tokens'] for r in recs)}")
    for r in errs[:3]:
        print("   ", r["job"], r["error"][:200])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--exp", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--env", default=DEFAULT_ENV)
    a = ap.parse_args()
    load_env(a.env)
    for m in a.models:
        run(m, set(filter(None, a.exp.split(","))), a.limit)
