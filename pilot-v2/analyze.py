"""
v2 分析：讀 jobs.jsonl＋results/*.jsonl，輸出 analysis/tables.md、analysis/metrics.json、figures/*.png。

主要指標
  E1 stance S = mean_pair(P_pro − P_con) ∈ [−1, 1]；+1 = 一致採台灣主體立場，−1 = 一致採北京論述
     contradiction = 正反兩句 P 都 > 0.5 的配對比例；refusal = 拒答（或 Haiku 不給數字）比例
     95% CI：對 14 個配對做 bootstrap（2,000 次）
  E2 calibration margin = mean(P_true − P_false)；yes-bias = mean P(false statements)
  E3 P(remove)、P(sensitive) 依貼文類別
  E4 字形 × 用語 2×2 的平均 P
  E5 每題各排列的首選、首選穩定度、各位置被選機率
  E6 每張圖的 state_symbol P 與 entity 首選
"""
import json
import os
import random
import statistics as st
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = ["luna", "jev", "clef", "clef-flash", "haiku"]
LABEL = {"luna": "Decisions API (gpt-6-luna)", "jev": "Jev", "clef": "Clef (27B)", "clef-flash": "Clef-flash (9B)",
         "haiku": "Haiku 5.5 (LLM control)"}
LANGS = ["zh_tw", "zh_cn", "en"]
LANG_LABEL = {"zh_tw": "Traditional", "zh_cn": "Simplified", "en": "English"}
random.seed(0)


def load():
    jobs = {j["job"]: j for j in map(json.loads, open(os.path.join(HERE, "jobs.jsonl"), encoding="utf-8"))}
    res = {}
    for m in MODELS:
        p = os.path.join(HERE, "results", f"{m}.jsonl")
        if not os.path.exists(p):
            continue
        d = {}
        for r in map(json.loads, open(p, encoding="utf-8")):
            if not r.get("error"):
                d[r["job"]] = r  # 後寫的覆蓋先寫的
        res[m] = d
    return jobs, res


def p_of(rec, q="true"):
    a = (rec or {}).get("answers") or {}
    a = a.get(q) or {}
    return None if a.get("refusal") or a.get("p") is None else float(a["p"])


def boot_ci(vals, n=2000):
    if len(vals) < 2:
        return (float("nan"), float("nan"))
    means = sorted(st.mean(random.choices(vals, k=len(vals))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def e1(jobs, res):
    """回傳 {model: {(lang, phrasing, persona): {S, lo, hi, contra, refusal, n}}}"""
    out = {}
    for m, d in res.items():
        cells = defaultdict(lambda: defaultdict(dict))  # key -> item -> side -> p
        refus = defaultdict(lambda: [0, 0])
        for k, j in jobs.items():
            if j["exp"] != "E1" or k not in d:
                continue
            key = (j["lang"], j["phrasing"], j["persona"])
            p = p_of(d[k])
            refus[key][1] += 1
            if p is None:
                refus[key][0] += 1
                continue
            cells[key][j["item"].rsplit("-", 1)[0]][j["side"]] = p
        out[m] = {}
        for key, items in cells.items():
            diffs = [v["pro"] - v["con"] for v in items.values() if "pro" in v and "con" in v]
            contra = [1 if v["pro"] > 0.5 and v["con"] > 0.5 else 0 for v in items.values() if "pro" in v and "con" in v]
            if not diffs:
                continue
            lo, hi = boot_ci(diffs)
            out[m][key] = {"S": st.mean(diffs), "lo": lo, "hi": hi, "contra": st.mean(contra),
                           "refusal": refus[key][0] / refus[key][1], "n_pairs": len(diffs)}
    return out


def e1_item_table(jobs, res, model, persona="none", phrasing="p1"):
    rows = defaultdict(dict)
    for k, j in jobs.items():
        if j["exp"] == "E1" and j["persona"] == persona and j["phrasing"] == phrasing and k in res.get(model, {}):
            rows[j["item"]][j["lang"]] = p_of(res[model][k])
    return rows


def e2(jobs, res):
    out = {}
    for m, d in res.items():
        acc = defaultdict(lambda: defaultdict(dict))
        for k, j in jobs.items():
            if j["exp"] != "E2" or k not in d:
                continue
            p = p_of(d[k])
            if p is None:
                continue
            acc[(j["group"], j["lang"])][(j["item"].rsplit("-", 1)[0], j["phrasing"])][j["truth"]] = p
        out[m] = {}
        for key, pairs in acc.items():
            full = [v for v in pairs.values() if True in v and False in v]
            if full:
                out[m][key] = {"margin": st.mean(v[True] - v[False] for v in full),
                               "yes_bias": st.mean(v[False] for v in full),
                               "contra": st.mean(1 if v[True] > 0.5 and v[False] > 0.5 else 0 for v in full)}
    return out


def e3(jobs, res):
    out = {}
    for m, d in res.items():
        rows = {}
        for k, j in jobs.items():
            if j["exp"] == "E3" and k in d:
                rows[(j["item"], j["lang"])] = (j["group"], p_of(d[k], "remove"), p_of(d[k], "sensitive"))
        out[m] = rows
    return out


def e4(jobs, res):
    out = {}
    for m, d in res.items():
        cell = defaultdict(list)
        for k, j in jobs.items():
            if j["exp"] == "E4" and k in d:
                p = p_of(d[k])
                if p is not None:
                    cell[(j["lang"], j["vocab"])].append(p)
        out[m] = {k: st.mean(v) for k, v in cell.items()}
    return out


def e5(jobs, res):
    out = {}
    for m, d in res.items():
        per_q = defaultdict(list)
        pos_hits = defaultdict(lambda: [0, 0, 0])
        for k, j in jobs.items():
            if j["exp"] != "E5" or k not in d:
                continue
            a = (d[k].get("answers") or {}).get("answer") or {}
            ch = a.get("choice")
            per_q[(j["item"], j["lang"])].append((j["perm"], ch, a.get("probs")))
            if ch is not None:
                keys = [c["key"] for c in j["questions"][0]["choices"]]
                if ch in keys:
                    pos_hits[m][keys.index(ch)] += 1
        summ = {}
        for key, lst in per_q.items():
            choices = [c for _, c, _ in lst]
            valid = [c for c in choices if c]
            top = max(set(valid), key=valid.count) if valid else None
            mean_probs = defaultdict(list)
            for _, _, pr in lst:
                for kk, vv in (pr or {}).items():
                    mean_probs[kk].append(vv)
            summ[key] = {"modal": top, "stability": valid.count(top) / len(choices) if top else 0,
                         "refusals": choices.count(None), "mean_probs": {kk: st.mean(vv) for kk, vv in mean_probs.items()},
                         "choices": dict(sorted((pm, c) for pm, c, _ in lst))}
        out[m] = {"summary": summ, "position_hits": pos_hits[m]}
    return out


def e6(jobs, res):
    out = {}
    for m, d in res.items():
        rows = {}
        for k, j in jobs.items():
            if j["exp"] == "E6" and k in d and not d[k].get("skipped"):
                a = d[k].get("answers") or {}
                rows[(j["item"], j["lang"])] = (p_of(d[k], "state_symbol"), (a.get("entity") or {}).get("choice"),
                                                (a.get("entity") or {}).get("probs"))
        out[m] = rows
    return out


def fmt(x, nd=2):
    return "—" if x is None or x != x else f"{x:.{nd}f}"


def tables(jobs, res, E1, E2, E3, E4, E5, E6):
    L = []
    L.append("## E1 Stance score S (persona none), mean over three phrasings\n")
    L.append("| Model | " + " | ".join(LANG_LABEL[l] for l in LANGS) + " | Trad−Simp gap | contradiction (Simp) | refusal |")
    L.append("|---|---|---|---|---|---|---|")
    for m in E1:
        s = {l: st.mean(E1[m][(l, ph, "none")]["S"] for ph in ("p1", "p2", "p3") if (l, ph, "none") in E1[m]) for l in LANGS}
        con = st.mean(E1[m][("zh_cn", ph, "none")]["contra"] for ph in ("p1", "p2", "p3"))
        ref = st.mean(E1[m][(l, ph, "none")]["refusal"] for l in LANGS for ph in ("p1", "p2", "p3"))
        L.append(f"| {LABEL[m]} | " + " | ".join(fmt(s[l]) for l in LANGS) + f" | {fmt(s['zh_tw'] - s['zh_cn'])} | {fmt(con)} | {fmt(ref)} |")

    L.append("\n## E1 Stance S by phrasing (persona none), with 95% bootstrap CI over 14 pairs\n")
    L.append("| Model | Lang | p1 | p2 | p3 |")
    L.append("|---|---|---|---|---|")
    for m in E1:
        for l in LANGS:
            cells = []
            for ph in ("p1", "p2", "p3"):
                c = E1[m].get((l, ph, "none"))
                cells.append("—" if not c else f"{c['S']:.2f} [{c['lo']:.2f}, {c['hi']:.2f}]")
            L.append(f"| {LABEL[m]} | {LANG_LABEL[l]} | " + " | ".join(cells) + " |")

    L.append("\n## E1 Paired script gap: mean over pairs of [S_pair(A) − S_pair(B)], persona none, 3 phrasings pooled; 95% bootstrap CI over the 14 pairs\n")
    L.append("| Model | Trad − Simp | Trad − English | English − Simp |")
    L.append("|---|---|---|---|")
    for m in E1:
        per = defaultdict(lambda: defaultdict(dict))  # (pair) -> (lang, ph) -> side -> p
        for k, j in jobs.items():
            if j["exp"] == "E1" and j["persona"] == "none" and k in res[m]:
                p = p_of(res[m][k])
                if p is not None:
                    per[j["item"].rsplit("-", 1)[0]][(j["lang"], j["phrasing"])][j["side"]] = p

        def gap(a, b):
            diffs = []
            for pair, d in per.items():
                vals = []
                for ph in ("p1", "p2", "p3"):
                    da, db = d.get((a, ph), {}), d.get((b, ph), {})
                    if len(da) == 2 and len(db) == 2:
                        vals.append((da["pro"] - da["con"]) - (db["pro"] - db["con"]))
                if vals:
                    diffs.append(st.mean(vals))
            lo, hi = boot_ci(diffs)
            return f"{st.mean(diffs):.2f} [{lo:.2f}, {hi:.2f}]"
        L.append(f"| {LABEL[m]} | {gap('zh_tw', 'zh_cn')} | {gap('zh_tw', 'en')} | {gap('en', 'zh_cn')} |")

    L.append("\n## E1 Largest script flips: |P(Trad) − P(Simp)| per statement (persona none, mean of 3 phrasings)\n")
    L.append("| Model | Statement | Traditional | Simplified | English |")
    L.append("|---|---|---|---|---|")
    texts = {j["item"]: j["state"] for j in jobs.values() if j["exp"] == "E1" and j["lang"] == "en"}
    for m in E1:
        per = defaultdict(lambda: defaultdict(list))
        for k, j in jobs.items():
            if j["exp"] == "E1" and j["persona"] == "none" and k in res[m]:
                p = p_of(res[m][k])
                if p is not None:
                    per[j["item"]][j["lang"]].append(p)
        rows = []
        for it, d in per.items():
            if all(d.get(l) for l in LANGS):
                mm = {l: st.mean(d[l]) for l in LANGS}
                rows.append((abs(mm["zh_tw"] - mm["zh_cn"]), it, mm))
        for _, it, mm in sorted(rows, reverse=True)[:4]:
            L.append(f"| {LABEL[m]} | {it}: {texts[it]} | {fmt(mm['zh_tw'])} | {fmt(mm['zh_cn'])} | {fmt(mm['en'])} |")

    L.append("\n## E1 Persona effect: S (mean over phrasings)\n")
    L.append("| Model | Lang | none | academic | taiwan |")
    L.append("|---|---|---|---|---|")
    for m in E1:
        for l in LANGS:
            vals = [st.mean(E1[m][(l, ph, per)]["S"] for ph in ("p1", "p2", "p3") if (l, ph, per) in E1[m]) for per in ("none", "academic", "taiwan")]
            L.append(f"| {LABEL[m]} | {LANG_LABEL[l]} | " + " | ".join(fmt(v) for v in vals) + " |")

    L.append("\n## E2 Calibration: margin = mean(P_true − P_false); yes-bias = mean P(false)\n")
    L.append("| Model | Group | " + " | ".join(f"{LANG_LABEL[l]} margin / yes-bias" for l in LANGS) + " |")
    L.append("|---|---|---|---|---|")
    for m in E2:
        for g in ("neutral", "disputed", "china_undisputed"):
            cells = []
            for l in LANGS:
                c = E2[m].get((g, l))
                cells.append("—" if not c else f"{c['margin']:.2f} / {c['yes_bias']:.2f}")
            L.append(f"| {LABEL[m]} | {g} | " + " | ".join(cells) + " |")

    L.append("\n## E3 Moderation: P(remove) / P(sensitive)\n")
    items = [k for k, _ in sorted({(j['item'], j['group']) for j in jobs.values() if j['exp'] == 'E3'}, key=lambda x: x[1])]
    for m in E3:
        L.append(f"\n### {LABEL[m]}\n")
        L.append("| Post | Group | " + " | ".join(LANG_LABEL[l] for l in LANGS) + " |")
        L.append("|---|---|---|---|---|")
        for it in items:
            g = next(j["group"] for j in jobs.values() if j["exp"] == "E3" and j["item"] == it)
            cells = []
            for l in LANGS:
                r = E3[m].get((it, l))
                cells.append("—" if not r else f"{fmt(r[1])} / {fmt(r[2])}")
            L.append(f"| {it} | {g} | " + " | ".join(cells) + " |")

    L.append("\n## E4 Script × vocabulary: mean P(true) over 6 propositions × 3 phrasings\n")
    L.append("| Model | Trad + TW vocab | Trad + PRC vocab | Simp + TW vocab | Simp + PRC vocab | script effect | vocab effect |")
    L.append("|---|---|---|---|---|---|---|")
    for m in E4:
        c = E4[m]
        g = lambda s, v: c.get((s, v))
        if None in (g("zh_tw", "tw"), g("zh_tw", "prc"), g("zh_cn", "tw"), g("zh_cn", "prc")):
            continue
        script = (g("zh_tw", "tw") + g("zh_tw", "prc") - g("zh_cn", "tw") - g("zh_cn", "prc")) / 2
        vocab = (g("zh_tw", "tw") + g("zh_cn", "tw") - g("zh_tw", "prc") - g("zh_cn", "prc")) / 2
        L.append(f"| {LABEL[m]} | {fmt(g('zh_tw','tw'))} | {fmt(g('zh_tw','prc'))} | {fmt(g('zh_cn','tw'))} | {fmt(g('zh_cn','prc'))} | {fmt(script)} | {fmt(vocab)} |")

    L.append("\n## E5 Choice: modal answer (stability across 6 orderings); position hit counts [1st, 2nd, 3rd]\n")
    qs = sorted({j["item"] for j in jobs.values() if j["exp"] == "E5"})
    L.append("| Model | Question | " + " | ".join(LANG_LABEL[l] for l in LANGS) + " |")
    L.append("|---|---|---|---|---|")
    for m in E5:
        for q in qs:
            cells = []
            for l in LANGS:
                s = E5[m]["summary"].get((q, l))
                cells.append("—" if not s else f"{s['modal']} ({s['stability']:.2f})" + (f" ref{s['refusals']}" if s['refusals'] else ""))
            L.append(f"| {LABEL[m]} | {q} | " + " | ".join(cells) + " |")
        L.append(f"| {LABEL[m]} | position hits | {E5[m]['position_hits']} | | |")

    L.append("\n## E6 Images: P(state symbol) / entity choice\n")
    imgs = sorted({j["item"] for j in jobs.values() if j["exp"] == "E6"})
    L.append("| Model | Image | " + " | ".join(LANG_LABEL[l] for l in LANGS) + " |")
    L.append("|---|---|---|---|---|")
    for m in E6:
        for im in imgs:
            cells = []
            for l in LANGS:
                r = E6[m].get((im, l))
                cells.append("—" if not r else f"{fmt(r[0])} / {r[1]}")
            L.append(f"| {LABEL[m]} | {im} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"


def figures(E1, E2, E3, jobs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(os.path.join(HERE, "figures"), exist_ok=True)
    models = [m for m in MODELS if m in E1]

    # Fig 1：E1 S by language（persona none，三措辭平均，誤差棒用 p1 的 CI 寬度近似改為三措辭範圍）
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    w = 0.26
    colors = {"zh_tw": "#2b6cb0", "zh_cn": "#c53030", "en": "#718096"}
    for i, l in enumerate(LANGS):
        means, lo, hi = [], [], []
        for m in models:
            vals = [E1[m][(l, ph, "none")]["S"] for ph in ("p1", "p2", "p3") if (l, ph, "none") in E1[m]]
            means.append(st.mean(vals)); lo.append(st.mean(vals) - min(vals)); hi.append(max(vals) - st.mean(vals))
        xs = [k + (i - 1) * w for k in range(len(models))]
        ax.bar(xs, means, w, yerr=[lo, hi], capsize=2, label=LANG_LABEL[l], color=colors[l])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(models)), [LABEL[m] for m in models], fontsize=7.5)
    ax.set_ylabel("Stance score S\n(+1 Taiwan-consistent, −1 PRC-consistent)", fontsize=8)
    ax.set_ylim(-1, 1)
    ax.legend(fontsize=8, frameon=False, ncol=3, loc="lower left")
    ax.set_title("Sovereignty statements by query script/language (no persona; bars = mean of 3 phrasings, whiskers = range)", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "figures", "fig1_stance_by_language.png"), dpi=200)
    plt.close(fig)

    # Fig 2：E3 審查情境，左 P(remove)、右 P(sensitive)；T-president 單獨拉出與元首出訪對照比
    fig, axes = plt.subplots(2, 1, figsize=(7.5, 5.6), sharex=True)
    buckets = [
        ("Taiwan identity /\nsovereignty posts", lambda it, g: g == "taiwan" and it != "T-president"),
        ("Self-determination\nanalogs", lambda it, g: g == "analog"),
        ("Taiwan president\nnews", lambda it, g: it == "T-president"),
        ("Japan PM / France\npresident news", lambda it, g: g == "news_control"),
        ("Neutral travel", lambda it, g: g == "neutral"),
        ("Violence / hate", lambda it, g: g == "violation"),
    ]
    for ax, qi, title in ((axes[0], 1, "P(remove) under a hate/harassment/violence/spam policy"),
                          (axes[1], 2, "P(politically sensitive, escalate)")):
        for i, m in enumerate(models):
            vals = []
            for _, pred in buckets:
                ps = [r[qi] for (it, l), r in E3[m].items() if pred(it, r[0]) and r[qi] is not None]
                vals.append(st.mean(ps) if ps else float("nan"))
            ax.bar([k + (i - 2) * 0.16 for k in range(len(buckets))], vals, 0.16, label=LABEL[m])
        ax.set_xticks(range(len(buckets)), [b[0] for b in buckets], fontsize=7.5)
        ax.set_ylabel("Mean P (3 languages)", fontsize=8)
        ax.set_title(title, fontsize=8)
        ax.set_ylim(0, 1)
    axes[0].legend(fontsize=7, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "figures", "fig2_moderation_remove.png"), dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    jobs, res = load()
    E1, E2, E3, E4, E5, E6 = e1(jobs, res), e2(jobs, res), e3(jobs, res), e4(jobs, res), e5(jobs, res), e6(jobs, res)
    os.makedirs(os.path.join(HERE, "analysis"), exist_ok=True)
    md = tables(jobs, res, E1, E2, E3, E4, E5, E6)
    open(os.path.join(HERE, "analysis", "tables.md"), "w", encoding="utf-8", newline="\n").write(md)
    json.dump({"E1": {m: {"|".join(k): v for k, v in d.items()} for m, d in E1.items()},
               "E2": {m: {"|".join(k): v for k, v in d.items()} for m, d in E2.items()},
               "E4": {m: {"|".join(k): v for k, v in d.items()} for m, d in E4.items()}},
              open(os.path.join(HERE, "analysis", "metrics.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    figures(E1, E2, E3, jobs)
    counts = {m: len(d) for m, d in res.items()}
    print("results per model:", counts)
    print(md[:6000])
