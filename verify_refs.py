"""論文外部事實的自動查核：抓一手頁面或官方 PDF，比對論文引用的關鍵字串，結果寫 analysis/ref-check.md（含查核時間與網址）。
關鍵字比對只證明該字串出現在來源中，不證明論文對來源的整體歸納；整體歸納由人工閱讀負責。"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (research reference check)"}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            data = r.read()
        if data[:4] == b"%PDF":
            import io
            from pypdf import PdfReader
            return re.sub(r"\s+", " ", " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages))
        return data.decode("utf-8", "replace")
    except Exception as e:
        return f"__ERROR__ {e}"


CHECKS = [
    ("OpenAI Decisions: only gpt-6-luna, public beta", "https://developers.openai.com/api/docs/guides/decisions",
     [r"gpt-6-luna.{0,30}is the only model", r"public beta"]),
    ("OpenAI forum announcement (date)", "https://community.openai.com/t/decisions-api-is-now-available-in-public-beta/1403877",
     [r"Decisions API is now available in Public Beta", r"2026-10-0[67]"]),
    ("TypeSafe docs: text only; English primary; CJK lower accuracy", "https://docs.typesafe.ai/concepts/state.md",
     [r"Jev accepts text only", r"primary training language is English", r"CJK scripts, are accepted but currently have lower accuracy"]),
    ("TypeSafe blog Jev announcement", "https://typesafe.ai/blog/introducing-system-one-models-and-jev",
     [r"Jev", r"2026-09-1[56]|September 1[56], 2026"]),
    ("Cloudflare Clef model doc (27B)", "https://developers.cloudflare.com/workers-ai/models/clef/index.md",
     [r"27B multimodal decision model"]),
    ("Cloudflare Clef-flash model doc (9B, images)", "https://developers.cloudflare.com/workers-ai/models/clef-flash/index.md",
     [r"9B multimodal decision model", r"images"]),
    ("Cloudflare blog Clef (date, Apache 2.0, Jev compatible)", "https://blog.cloudflare.com/clef-decision-models/",
     [r"2026-10-01", r"Apache[ -]2\.0", r"Jev"]),
    ("Hugging Face Cloudflare/clef license", "https://huggingface.co/api/models/Cloudflare/clef", [r"apache-2\.0"]),
    ("arXiv 2602.06371 (Ko): 15 of 17", "https://arxiv.org/abs/2602.06371", [r"15 out of 17 tested models", r"Ju-Chun Ko"]),
    ("hsiaoa benchmark license", "https://api.github.com/repos/hsiaoa/ai-taiwan-sovereignty-benchmark", [r'"spdx_id": ?"MIT"']),
    ("hsiaoa FINDINGS_2026_08 script gate + persona as jailbreak",
     "https://raw.githubusercontent.com/hsiaoa/ai-taiwan-sovereignty-benchmark/main/FINDINGS_2026_08.md",
     [r"字體閘門", r"越獄"]),
    ("PoPETs 2025 Ahmed, Knockel, Greenstadt", "https://petsymposium.org/popets/2025/popets-2025-0122.php",
     [r"An Analysis of Chinese Censorship Bias in LLMs", r"Knockel", r"Greenstadt"]),
    ("Aleph Alpha blog (date)", "https://aleph-alpha.com/en/blog/training-on-the-party-line/", [r"2026-09-28", r"967"]),
    ("Lin 2024 HF blog", "https://huggingface.co/blog/leonardlin/chinese-llm-censorship-analysis", [r"2024", r"Qwen 2"]),
    ("UN OHCHR Xinjiang assessment, 31 Aug 2022, para. 143 (official PDF)",
     "https://www.ohchr.org/sites/default/files/documents/countries/2022-08-31/22-08-31-final-assesment.pdf",
     [r"Serious human rights violations have been committed in XUAR"]),
    ("PCA Press Release No. 11, 12 Jul 2016 (official PDF)",
     "https://docs.pca-cpa.org/2016/07/PH-CN-20160712-Press-Release-No-11-English.pdf",
     [r"no legal basis for China to claim historic rights to resources"]),
    ("PoPETs 2025 DOI resolves", "https://doi.org/10.56553/popets-2025-0122", [r"Censorship Bias"]),
    ("NCCU Election Study Center: unification-independence trend page (status-quo options)",
     "https://esc.nccu.edu.tw/PageDoc?fid=7805", [r"統獨立場"]),
]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lines = [f"# Reference check ({datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')})\n",
             "| Claim | URL | Pattern | Found |", "|---|---|---|---|"]
    for name, url, pats in CHECKS:
        t = get(url)
        for p in pats:
            ok = "fetch error" if t.startswith("__ERROR__") else ("yes" if re.search(p, t) else "NO")
            lines.append(f"| {name} | {url} | `{p}` | {ok} |")
            print(ok.ljust(11), name, "|", p)
    os.makedirs(os.path.join(HERE, "analysis"), exist_ok=True)
    open(os.path.join(HERE, "analysis", "ref-check.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
