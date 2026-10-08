"""
v3 分析：讀 jobs.jsonl＋results/*.jsonl，輸出 analysis/tables.md、analysis/metrics.json、figures/*.png。

處理順序
  1. 每個 (model, job, question) 的 3 次重複：記錄穩定度；P 取非缺漏重複的平均（全缺漏＝該格缺漏）
  2. 各實驗的指標都以「題目（statement pair／proposition／post）」為單位做 bootstrap（10,000 次），
     區間是對這組固定題目的重抽樣描述區間，不是母體推論
  3. 缺漏一律列出 n；E1 另做「缺漏視為 0.5」的敏感度分析

指標
  E1 index S = mean_pair(P_pro − P_con) ∈ [−1, 1]（本研究的操作性指標，不是潛在立場量表）；另分三個子量表
     paired script gap = mean_pair[s_pair(A) − s_pair(B)]，三種措辭先在 pair 內平均
  E2 依組別：同 S 定義（pro＝國際主流／自治方），以及 Trad−Simp gap；neutral／china_undisputed 另報 yes-rate on false
  E3 三題（remove／sensitive／escalate）逐貼文；N-TW 與四個對照國逐字配對比較
  E4 2×2 平均與 script／vocab 效果（bootstrap over 6 propositions）
  E5 首選、跨 6 種排列的穩定度、平均機率
  E6 每張圖
"""
import hashlib
import json
import os
import random
import statistics as st
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = ["luna", "jev", "clef", "clef-flash", "haiku"]
DECISION = ["luna", "jev", "clef", "clef-flash"]
LABEL = {"luna": "Decisions API (gpt-6-luna)", "jev": "Jev", "clef": "Clef (27B)", "clef-flash": "Clef-flash (9B)",
         "haiku": "Haiku 5.5 (LLM control)"}
SHORT = {"luna": "Decisions API", "jev": "Jev", "clef": "Clef", "clef-flash": "Clef-flash", "haiku": "Haiku (control)"}
LANGS = ["zh_tw", "zh_cn", "en"]
LL = {"zh_tw": "Traditional", "zh_cn": "Simplified", "en": "English"}
PHS = ("p1", "p2", "p3")
B = 10000
REPS = 3  # run.py 的預設重複次數
random.seed(0)


def load():
    jobs = {j["job"]: j for j in map(json.loads, open(os.path.join(HERE, "jobs.jsonl"), encoding="utf-8"))}
    raw = {}
    for m in MODELS:
        p = os.path.join(HERE, "results", f"{m}.jsonl")
        if os.path.exists(p):
            raw[m] = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    return jobs, raw


def aggregate(jobs, raw):
    """回傳 agg[m][job][q] = {"p": mean or None, "reps": [...], "choice": modal, "choices": [...], "probs": mean dict, "status": ...}
    以及 stability 統計"""
    agg, stab = {}, {}
    for m, recs in raw.items():
        by = defaultdict(lambda: defaultdict(list))
        for r in recs:
            if r.get("error") or r.get("skipped") or not r.get("answers"):
                continue
            for q, a in r["answers"].items():
                by[r["job"]][q].append(a)
        out, ident, tot, ranges, flips = {}, 0, 0, [], 0
        ch_tot = ch_same = 0
        for job, qs in by.items():
            out[job] = {}
            for q, lst in qs.items():
                ps = [a["p"] for a in lst if a.get("p") is not None]
                chs = [a.get("choice") for a in lst if a.get("choice")]
                probs = defaultdict(list)
                for a in lst:
                    for k, v in (a.get("probs") or {}).items():
                        probs[k].append(v)
                n_missing = sum(1 for a in lst if a.get("p") is None and not a.get("choice"))
                is_prob = not chs and not probs
                out[job][q] = {"p": st.mean(ps) if ps else None, "reps": ps, "n_reps": len(lst), "n_missing": n_missing,
                               # 敏感度分析用：以預期的 REPS 個重複為分母，無效回覆與整筆遺失的重複都視為 0.5
                               "p_imp": (sum(ps) + 0.5 * (REPS - len(ps))) / REPS if is_prob else None,
                               "choice": modal(chs), "choices": chs,
                               "probs": {k: st.mean(v) for k, v in probs.items()}}
                if len(ps) >= 2:
                    tot += 1
                    rg = max(ps) - min(ps)
                    ranges.append(rg)
                    ident += rg == 0
                    flips += (max(ps) > 0.5) != (min(ps) > 0.5)
                elif len(chs) >= 2:
                    ch_tot += 1
                    ch_same += len(set(chs)) == 1
            # 有些重複答出、有些缺漏：記為不一致
        # 部分缺漏：有至少一個有效回覆、但不足 REPS 個（無效回覆或整筆遺失都算）
        mixed = sum(1 for job, qs in out.items() for q, v in qs.items()
                    if v["reps"] and len(v["reps"]) < REPS and v["choice"] is None)
        agg[m] = out
        stab[m] = {"cells": tot, "identical": ident, "max_range": max(ranges) if ranges else None,
                   "p95_range": sorted(ranges)[int(0.95 * len(ranges))] if ranges else None,
                   "threshold_flips": flips, "mixed_missing": mixed, "choice_cells": ch_tot, "choice_same": ch_same}
    return agg, stab


def modal(chs):
    """最常見的選項；最高票數平手時回傳 'tie:a/b'（不任意挑一個）"""
    if not chs:
        return None
    c = Counter(chs).most_common()
    top = [k for k, v in c if v == c[0][1]]
    return top[0] if len(top) == 1 else "tie:" + "/".join(sorted(top))


def P(agg, m, job, q="true", imputed=False):
    v = agg.get(m, {}).get(job, {}).get(q) or {}
    return v.get("p_imp") if imputed else v.get("p")


def boot(vals, n=B):
    """百分位 bootstrap；亂數種子由資料本身決定，同一組數字在任何表格都得到相同區間"""
    if len(vals) < 2:
        return float("nan"), float("nan")
    seed = int(hashlib.sha256(json.dumps([round(v, 10) for v in vals]).encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    ms = sorted(st.mean(rng.choices(vals, k=len(vals))) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n) - 1]


def fmt(x, nd=2):
    return "—" if x is None or x != x else f"{x:.{nd}f}"


def ci(vals):
    if not vals:
        return "—"
    lo, hi = boot(vals)
    return f"{st.mean(vals):.2f} [{lo:.2f}, {hi:.2f}]"


# ---------- E1 ----------
def pair_values(jobs, agg, m, exp, cond, missing_as=None):
    """cond(job)->bool；回傳 {pair: {(lang, ph): s}}"""
    tmp = defaultdict(lambda: defaultdict(dict))
    for k, j in jobs.items():
        if j["exp"] != exp or not cond(j):
            continue
        if missing_as is None:
            p = P(agg, m, k)
            if p is None:
                continue
        else:  # 敏感度分析：每一次缺漏的重複都補 missing_as（整格缺漏亦同）
            p = P(agg, m, k, imputed=True)
            if p is None:
                p = missing_as
        tmp[j["pair"]][(j["lang"], j["phrasing"])][j["side"]] = p
    return {pair: {key: d["pro"] - d["con"] for key, d in cells.items() if "pro" in d and "con" in d} for pair, cells in tmp.items()}


def S_cell(pv, lang, phrasings=PHS):
    """每個 pair 先在指定措辭內平均，再對 pair 平均；回傳 (S, per-pair list)"""
    per = []
    for pair, cells in pv.items():
        vals = [cells[(lang, ph)] for ph in phrasings if (lang, ph) in cells]
        if vals:
            per.append(st.mean(vals))
    return (st.mean(per) if per else None), per


def gap_list(pv, a, b):
    out = []
    for pair, cells in pv.items():
        vals = [cells[(a, ph)] - cells[(b, ph)] for ph in PHS if (a, ph) in cells and (b, ph) in cells]
        if vals:
            out.append(st.mean(vals))
    return out


def contra_rate(jobs, agg, m, lang, persona="none"):
    tmp = defaultdict(dict)
    for k, j in jobs.items():
        if j["exp"] == "E1" and j["lang"] == lang and j["persona"] == persona:
            p = P(agg, m, k)
            if p is not None:
                tmp[(j["pair"], j["phrasing"])][j["side"]] = p
    full = [d for d in tmp.values() if len(d) == 2]
    return (st.mean(1 if d["pro"] > 0.5 and d["con"] > 0.5 else 0 for d in full) if full else None), len(full)


def missing_counts(jobs, agg, raw, m, exp):
    n_cells = n_missing = 0
    for k, j in jobs.items():
        if j["exp"] != exp:
            continue
        for q in j["questions"]:
            v = agg.get(m, {}).get(k, {}).get(q["name"])
            n_cells += 1
            if v is None or (v["p"] is None and v["choice"] is None):
                n_missing += 1
    return n_missing, n_cells


def tables(jobs, agg, raw, stab):
    L = []
    w = L.append

    w("## Run summary\n")
    w("| Model | job-runs | HTTP calls | retries | skipped (local) | transport errors | input tokens | model id(s) | first | last |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for m, recs in raw.items():
        ids = Counter(r.get("model_version") for r in recs if r.get("model_version"))
        w(f"| {SHORT[m]} | {len(recs)} | {sum(r['http_calls'] for r in recs)} | {sum(r['retries'] for r in recs)} | "
          f"{sum(1 for r in recs if r.get('skipped'))} | {sum(1 for r in recs if r.get('error'))} | {sum(r['tokens'] for r in recs)} | "
          f"{', '.join(f'{k} ({v})' for k, v in ids.most_common(2))} | {min(r['started'] for r in recs)} | {max(r['finished'] for r in recs)} |")

    w("\n## Repeat stability (3 repetitions per job and question)\n")
    w("| Model | probability cells (≥2 answers) | identical across reps | max range of P | 95th pct range | cells crossing 0.5 | choice cells | same choice in all reps | cells partly missing |")
    w("|---|---|---|---|---|---|---|---|---|")
    for m, s in stab.items():
        w(f"| {SHORT[m]} | {s['cells']} | {s['identical']} ({s['identical'] / max(s['cells'], 1):.1%}) | {fmt(s['max_range'])} | "
          f"{fmt(s['p95_range'])} | {s['threshold_flips']} | {s['choice_cells']} | {s['choice_same']} | {s['mixed_missing']} |")

    w("\n## Missing answers (refusal, unparsed, or absent), after aggregating repetitions\n")
    w("| Model | " + " | ".join(f"E{i}" for i in range(1, 7)) + " |")
    w("|---|" + "---|" * 6)
    for m in agg:
        cells = []
        for i in range(1, 7):
            mi, n = missing_counts(jobs, agg, raw, m, f"E{i}")
            cells.append(f"{mi}/{n}")
        w(f"| {SHORT[m]} | " + " | ".join(cells) + " |")

    w("\n## Missing answers at the run level (question × repetition), by experiment; Jev E6 is not applicable (text-only)\n")
    w("| Model | " + " | ".join(f"E{i}" for i in range(1, 7)) + " | cells partly missing (E1/E2/E4) |")
    w("|---|" + "---|" * 7)
    for m in agg:
        cells = []
        for i in range(1, 7):
            tot = mi = 0
            for k, j in jobs.items():
                if j["exp"] != f"E{i}":
                    continue
                for q in j["questions"]:
                    v = agg[m].get(k, {}).get(q["name"])
                    n = v["n_reps"] if v else 0
                    tot += 3
                    mi += (3 - n) + (v["n_missing"] if v else 0)
            cells.append(f"{mi}/{tot}")
        part = []
        for e in ("E1", "E2", "E4"):
            part.append(str(sum(1 for k, j in jobs.items() if j["exp"] == e
                                for q in j["questions"]
                                if (v := agg[m].get(k, {}).get(q["name"])) and 0 < v["n_missing"] < v["n_reps"])))
        w(f"| {SHORT[m]} | " + " | ".join(cells) + f" | {'/'.join(part)} |")

    # E1 main
    w("\n## E1 Index S (no persona; pair values averaged over 3 phrasings), with item-bootstrap intervals and n pairs\n")
    w("| Model | Traditional | Simplified | English | Trad−Simp gap | Eng−Simp gap | Trad−Eng gap | contradictory pairs (Trad / Simp / Eng) |")
    w("|---|---|---|---|---|---|---|---|")
    res = {}
    for m in agg:
        pv = pair_values(jobs, agg, m, "E1", lambda j: j["persona"] == "none")
        cells = []
        for l in LANGS:
            s, per = S_cell(pv, l)
            cells.append(f"{ci(per)} (n={len(per)})")
        g1, g2, g3 = gap_list(pv, "zh_tw", "zh_cn"), gap_list(pv, "en", "zh_cn"), gap_list(pv, "zh_tw", "en")
        cr = [contra_rate(jobs, agg, m, l) for l in LANGS]
        w(f"| {SHORT[m]} | " + " | ".join(cells) + f" | {ci(g1)} (n={len(g1)}) | {ci(g2)} | {ci(g3)} | "
          + " / ".join(f"{fmt(c[0] * 100 if c[0] is not None else None, 0)}%" for c in cr) + " |")
        res[m] = {"S": {l: S_cell(pv, l)[0] for l in LANGS}, "gap_ts": st.mean(g1) if g1 else None}

    w("\n## E1 Sensitivity: missing answers treated as P = 0.5\n")
    w("| Model | Traditional | Simplified | English | Trad−Simp gap |")
    w("|---|---|---|---|---|")
    for m in agg:
        pv = pair_values(jobs, agg, m, "E1", lambda j: j["persona"] == "none", missing_as=0.5)
        w(f"| {SHORT[m]} | " + " | ".join(fmt(S_cell(pv, l)[0]) for l in LANGS) + f" | {ci(gap_list(pv, 'zh_tw', 'zh_cn'))} |")

    w("\n## E1 Index S by phrasing (no persona)\n")
    w("| Model | Lang | p1 | p2 | p3 |")
    w("|---|---|---|---|---|")
    for m in agg:
        pv = pair_values(jobs, agg, m, "E1", lambda j: j["persona"] == "none")
        for l in LANGS:
            w(f"| {SHORT[m]} | {LL[l]} | " + " | ".join(fmt(S_cell(pv, l, (ph,))[0]) for ph in PHS) + " |")
    w("\n## E1 Trad−Simp gap by phrasing (no persona)\n")
    w("| Model | p1 | p2 | p3 |")
    w("|---|---|---|---|")
    for m in agg:
        pv = pair_values(jobs, agg, m, "E1", lambda j: j["persona"] == "none")
        row = []
        for ph in PHS:
            vals = [c[("zh_tw", ph)] - c[("zh_cn", ph)] for c in pv.values() if ("zh_tw", ph) in c and ("zh_cn", ph) in c]
            row.append(ci(vals))
        w(f"| {SHORT[m]} | " + " | ".join(row) + " |")

    w("\n## E1 Subscales (no persona)\n")
    w("| Model | Subscale (pairs) | Traditional | Simplified | English | Trad−Simp gap |")
    w("|---|---|---|---|---|---|")
    for m in agg:
        for sub in ("status", "institutional", "normative"):
            pv = pair_values(jobs, agg, m, "E1", lambda j, sub=sub: j["persona"] == "none" and j["subscale"] == sub)
            w(f"| {SHORT[m]} | {sub} ({len(pv)}) | " + " | ".join(fmt(S_cell(pv, l)[0]) for l in LANGS)
              + f" | {ci(gap_list(pv, 'zh_tw', 'zh_cn'))} |")

    w("\n## E1 Persona: S by language\n")
    w("| Model | Lang | none | academic | taiwan |")
    w("|---|---|---|---|---|")
    for m in agg:
        for l in LANGS:
            row = []
            for per in ("none", "academic", "taiwan"):
                pv = pair_values(jobs, agg, m, "E1", lambda j, per=per: j["persona"] == per)
                row.append(fmt(S_cell(pv, l)[0]))
            w(f"| {SHORT[m]} | {LL[l]} | " + " | ".join(row) + " |")
    w("\n## E1 Persona: Trad−Simp gap\n")
    w("| Model | none | academic | taiwan |")
    w("|---|---|---|---|")
    for m in agg:
        row = []
        for per in ("none", "academic", "taiwan"):
            pv = pair_values(jobs, agg, m, "E1", lambda j, per=per: j["persona"] == per)
            row.append(ci(gap_list(pv, "zh_tw", "zh_cn")))
        w(f"| {SHORT[m]} | " + " | ".join(row) + " |")

    w("\n## E1 Item-level P (no persona, mean of phrasings and repetitions)\n")
    texts = {j["item"]: j["state"] for j in jobs.values() if j["exp"] == "E1" and j["lang"] == "en"}
    items = sorted(texts)
    w("| Item | Statement | " + " | ".join(f"{SHORT[m]} T/S/E" for m in agg) + " |")
    w("|---|---|" + "---|" * len(agg))
    for it in items:
        row = []
        for m in agg:
            vals = []
            for l in LANGS:
                ps = [P(agg, m, f"E1|{it}|{l}|{ph}|none") for ph in PHS]
                ps = [p for p in ps if p is not None]
                vals.append(fmt(st.mean(ps)) if ps else "—")
            row.append("/".join(vals))
        w(f"| {it} | {texts[it]} | " + " | ".join(row) + " |")

    # E2
    w("\n## E2 Controls: index S by group (pro − con), and Trad−Simp gap; compare with E1\n")
    w("| Model | Group (pairs) | Traditional | Simplified | English | Trad−Simp gap | Eng−Simp gap |")
    w("|---|---|---|---|---|---|---|")
    for m in agg:
        pv1 = pair_values(jobs, agg, m, "E1", lambda j: j["persona"] == "none")
        w(f"| {SHORT[m]} | Taiwan E1 ({len(pv1)}) | " + " | ".join(fmt(S_cell(pv1, l)[0]) for l in LANGS)
          + f" | {ci(gap_list(pv1, 'zh_tw', 'zh_cn'))} | {ci(gap_list(pv1, 'en', 'zh_cn'))} |")
        for g in ("prc_sensitive", "disputed", "china_undisputed", "neutral"):
            pv = pair_values(jobs, agg, m, "E2", lambda j, g=g: j["group"] == g)
            w(f"| {SHORT[m]} | {g} ({len(pv)}) | " + " | ".join(fmt(S_cell(pv, l)[0]) for l in LANGS)
              + f" | {ci(gap_list(pv, 'zh_tw', 'zh_cn'))} | {ci(gap_list(pv, 'en', 'zh_cn'))} |")
    w("\n## E2 Item-level P(pro) / P(con), mean of phrasings\n")
    pairs = sorted({j["pair"] for j in jobs.values() if j["exp"] == "E2"})
    for m in agg:
        w(f"\n### {LABEL[m]}\n")
        w("| Pair | Group | Traditional | Simplified | English |")
        w("|---|---|---|---|---|")
        for pr in pairs:
            g = next(j["group"] for j in jobs.values() if j["exp"] == "E2" and j["pair"] == pr)
            row = []
            for l in LANGS:
                vv = []
                for side in ("pro", "con"):
                    ps = [P(agg, m, f"E2|{pr}-{side}|{l}|{ph}") for ph in PHS]
                    ps = [p for p in ps if p is not None]
                    vv.append(fmt(st.mean(ps)) if ps else "—")
                row.append(" / ".join(vv))
            w(f"| {pr} | {g} | " + " | ".join(row) + " |")

    # E3
    w("\n## E3 Moderation, item level: P(remove) / P(sensitive) / P(escalate)\n")
    posts = [j["item"] for j in sorted(jobs.values(), key=lambda j: j["job"]) if j["exp"] == "E3" and j["lang"] == "en"]
    for m in agg:
        w(f"\n### {LABEL[m]}\n")
        w("| Post | Group | Traditional | Simplified | English |")
        w("|---|---|---|---|---|")
        for it in posts:
            g = next(j["group"] for j in jobs.values() if j["exp"] == "E3" and j["item"] == it)
            row = []
            for l in LANGS:
                k = f"E3|{it}|{l}"
                row.append(" / ".join(fmt(P(agg, m, k, q)) for q in ("remove", "sensitive", "escalate")))
            w(f"| {it} | {g} | " + " | ".join(row) + " |")
    w("\n## E3 Matched head-of-state news (\"The president of X is visiting Paraguay today\"): Taiwan minus mean of 4 controls\n")
    w("| Model | Question | Taiwan (T/S/E) | Controls mean (T/S/E) | Difference, mean over 3 languages |")
    w("|---|---|---|---|---|")
    ctrls = ["N-KR", "N-PH", "N-CL", "N-PL"]
    for m in agg:
        for q in ("sensitive", "escalate", "remove"):
            tw = [P(agg, m, f"E3|N-TW|{l}", q) for l in LANGS]
            cm = []
            for l in LANGS:
                vs = [P(agg, m, f"E3|{c}|{l}", q) for c in ctrls]
                vs = [v for v in vs if v is not None]
                cm.append(st.mean(vs) if vs else None)
            diffs = [a - b for a, b in zip(tw, cm) if a is not None and b is not None]
            w(f"| {SHORT[m]} | {q} | " + "/".join(fmt(x) for x in tw) + " | " + "/".join(fmt(x) for x in cm)
              + f" | {fmt(st.mean(diffs)) if diffs else '—'} |")

    # E4
    w("\n## E4 Script × vocabulary (6 propositions × 3 phrasings; all propositions describe the same institutional fact in both vocabularies)\n")
    w("| Model | Trad+TW | Trad+PRC | Simp+TW | Simp+PRC | script effect [CI over props] | vocabulary effect [CI] |")
    w("|---|---|---|---|---|---|---|")
    props = sorted({j["item"] for j in jobs.values() if j["exp"] == "E4"})
    for m in agg:
        cell = {}
        per_prop = defaultdict(dict)
        for s in ("zh_tw", "zh_cn"):
            for v in ("tw", "prc"):
                vals = []
                for pr in props:
                    ps = [P(agg, m, f"E4|{pr}|{s}|{v}|{ph}") for ph in PHS]
                    ps = [p for p in ps if p is not None]
                    if ps:
                        per_prop[pr][(s, v)] = st.mean(ps)
                        vals.append(st.mean(ps))
                cell[(s, v)] = st.mean(vals) if vals else None
        se = [(d[("zh_tw", "tw")] + d[("zh_tw", "prc")] - d[("zh_cn", "tw")] - d[("zh_cn", "prc")]) / 2 for d in per_prop.values() if len(d) == 4]
        ve = [(d[("zh_tw", "tw")] + d[("zh_cn", "tw")] - d[("zh_tw", "prc")] - d[("zh_cn", "prc")]) / 2 for d in per_prop.values() if len(d) == 4]
        w(f"| {SHORT[m]} | {fmt(cell[('zh_tw', 'tw')])} | {fmt(cell[('zh_tw', 'prc')])} | {fmt(cell[('zh_cn', 'tw')])} | "
          f"{fmt(cell[('zh_cn', 'prc')])} | {ci(se)} | {ci(ve)} |")

    # E5
    w("\n## E5 Choice: modal answer, share of the 18 runs (6 orderings × 3 reps) choosing it, mean probabilities\n")
    w("| Model | Question | Lang | modal | share | mean probabilities | missing |")
    w("|---|---|---|---|---|---|---|")
    qs = sorted({j["item"] for j in jobs.values() if j["exp"] == "E5"})
    for m in agg:
        for q in qs:
            for l in LANGS:
                chs, probs, miss = [], defaultdict(list), 0
                for k, j in jobs.items():
                    if j["exp"] == "E5" and j["item"] == q and j["lang"] == l:
                        v = agg.get(m, {}).get(k, {}).get("answer")
                        if not v:
                            miss += 3
                            continue
                        chs += v["choices"]
                        miss += v["n_reps"] - len(v["choices"])
                        for kk, vv in v["probs"].items():
                            probs[kk].append(vv)
                mo = modal(chs)
                share = (max(Counter(chs).values()) / (len(chs) + miss)) if chs else 0
                w(f"| {SHORT[m]} | {q} | {LL[l]} | {mo or '—'} | {share:.2f} | "
                  + ", ".join(f"{k} {st.mean(v):.2f}" for k, v in sorted(probs.items())) + f" | {miss} |")

    w("\n## E5 Choice by option ordering (3 reps each; ordering digits index the original option list): cells where not every ordering gives the same modal answer\n")
    w("| Model | Question | Lang | ordering → choices over 3 reps |")
    w("|---|---|---|---|")
    for m in agg:
        for q in qs:
            for l in LANGS:
                per = {}
                for k, j in jobs.items():
                    if j["exp"] == "E5" and j["item"] == q and j["lang"] == l:
                        v = agg.get(m, {}).get(k, {}).get("answer")
                        per[j["perm"]] = v["choices"] if v else []
                modals = {modal(c) for c in per.values()}
                if len(modals) > 1:
                    w(f"| {SHORT[m]} | {q} | {LL[l]} | " + "; ".join(f"{pm}: {'/'.join(c)}" for pm, c in sorted(per.items())) + " |")

    # E6
    w("\n## E6 Images: P(state symbol) / modal entity\n")
    w("| Model | Image | Traditional | Simplified | English |")
    w("|---|---|---|---|---|")
    imgs = sorted({j["item"] for j in jobs.values() if j["exp"] == "E6"})
    for m in agg:
        for im in imgs:
            row = []
            for l in LANGS:
                k = f"E6|{im}|{l}"
                v = agg.get(m, {}).get(k)
                row.append("—" if not v else f"{fmt(P(agg, m, k, 'state_symbol'))} / {(v.get('entity') or {}).get('choice')}")
            w(f"| {SHORT[m]} | {im} | " + " | ".join(row) + " |")
    return "\n".join(L) + "\n", res


def figures(jobs, agg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(os.path.join(HERE, "figures"), exist_ok=True)
    models = [m for m in MODELS if m in agg]
    colors = {"zh_tw": "#2b6cb0", "zh_cn": "#c53030", "en": "#718096"}

    # Fig 1：E1 S by language with item-bootstrap intervals
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    wd = 0.26
    for i, l in enumerate(LANGS):
        means, lo, hi = [], [], []
        for m in models:
            pv = pair_values(jobs, agg, m, "E1", lambda j: j["persona"] == "none")
            s, per = S_cell(pv, l)
            a, b = boot(per, 2000)
            means.append(s); lo.append(s - a); hi.append(b - s)
        ax.bar([k + (i - 1) * wd for k in range(len(models))], means, wd, yerr=[lo, hi], capsize=2, label=LL[l], color=colors[l])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(models)), [LABEL[m] for m in models], fontsize=7.5)
    ax.set_ylabel("Index S\n(+1 self-governance-aligned, −1 PRC-position-aligned)", fontsize=8)
    ax.set_ylim(-1, 1)
    ax.legend(fontsize=8, frameon=False, ncol=3, loc="lower left")
    ax.set_title("E1 sovereignty pairs by query script, no persona (whiskers: 95% item-bootstrap interval, 14 pairs)", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "figures", "fig1_index_by_script.png"), dpi=200)
    plt.close(fig)

    # Fig 2：Trad−Simp gap by item group (Taiwan vs PRC-sensitive vs disputed vs neutral)
    groups = [("Taiwan (E1)", "E1", None), ("PRC-sensitive,\nnon-Taiwan", "E2", "prc_sensitive"),
              ("Non-China\nsovereignty disputes", "E2", "disputed"), ("China-related,\nundisputed", "E2", "china_undisputed"),
              ("Neutral facts", "E2", "neutral")]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    for i, m in enumerate(models):
        vals = []
        for _, exp, g in groups:
            cond = (lambda j: j["persona"] == "none") if exp == "E1" else (lambda j, g=g: j["group"] == g)
            gl = gap_list(pair_values(jobs, agg, m, exp, cond), "zh_tw", "zh_cn")
            vals.append(st.mean(gl) if gl else float("nan"))
        ax.bar([k + (i - 2) * 0.16 for k in range(len(groups))], vals, 0.16, label=LABEL[m])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(groups)), [g[0] for g in groups], fontsize=7.5)
    ax.set_ylabel("Traditional − Simplified gap\nin pair index (pro − con)", fontsize=8)
    ax.legend(fontsize=6.5, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "figures", "fig2_script_gap_by_group.png"), dpi=200)
    plt.close(fig)

    # Fig 3：matched head-of-state news
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 3.0), sharey=True)
    countries = [("N-TW", "Taiwan"), ("N-KR", "S. Korea"), ("N-PH", "Philippines"), ("N-CL", "Chile"), ("N-PL", "Poland")]
    for ax, q, title in ((axes[0], "sensitive", "P(topic politically sensitive)"), (axes[1], "escalate", "P(escalate for human review)")):
        for i, m in enumerate(models):
            vals = []
            for c, _ in countries:
                ps = [P(agg, m, f"E3|{c}|{l}", q) for l in LANGS]
                ps = [p for p in ps if p is not None]
                vals.append(st.mean(ps) if ps else float("nan"))
            ax.bar([k + (i - 2) * 0.16 for k in range(len(countries))], vals, 0.16, label=LABEL[m])
        ax.set_xticks(range(len(countries)), [c[1] for c in countries], fontsize=7.5)
        ax.set_title(title, fontsize=8)
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("Mean over 3 languages", fontsize=8)
    axes[1].legend(fontsize=6, frameon=False, loc="upper right")
    fig.suptitle("E3 \"The president of X is visiting Paraguay today\"", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "figures", "fig3_matched_news.png"), dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    jobs, raw = load()
    agg, stab = aggregate(jobs, raw)
    os.makedirs(os.path.join(HERE, "analysis"), exist_ok=True)
    md, res = tables(jobs, agg, raw, stab)
    open(os.path.join(HERE, "analysis", "tables.md"), "w", encoding="utf-8", newline="\n").write(md)
    json.dump({"stability": stab, "E1": res}, open(os.path.join(HERE, "analysis", "metrics.json"), "w", encoding="utf-8", newline="\n"),
              ensure_ascii=False, indent=1)
    figures(jobs, agg)
    print({m: len(r) for m, r in raw.items()})
