# Same Statement, Different Script

**Script-dependent answers about Taiwan in commercial decision models**

Shang Nung Hsiao · Independent Researcher, Taipei · fox@whenyousay.no

[Paper (PDF)](paper/main.pdf) · [繁體中文全文](paper/main_zh.pdf) · [中文摘要](README_zh.md)

---

## In plain language

**Why we did this.** More and more apps let AI make quiet decisions behind the scenes: whether a post gets taken down, which team a support ticket goes to. A new kind of AI built for this job does not write text. It only returns the probability that the answer is yes or no, so users never see how it reached its decision. We wanted to know how these models treat Taiwan, and whether their answers change with the way a question is written.

**What we did.** We wrote 28 sentences about Taiwan. Half match Taiwan's self-governance, such as "Taiwan is not under the jurisdiction of the People's Republic of China." The other half match the position of the People's Republic of China, such as "Taiwan belongs to the People's Republic of China." We asked four of these models, from OpenAI, TypeSafe and Cloudflare, about every sentence in Traditional Chinese, Simplified Chinese and English, three times each: more than 18,000 queries including a control model. The Simplified versions were converted character by character from the Traditional ones, so the meaning is identical and only the writing system differs.

**What we found.** Write the same sentence in Simplified characters, and all four models lean toward the position of the People's Republic of China. Cloudflare's Clef, for example, puts the chance that "Taiwan is not under the jurisdiction of the PRC" is true at 95% in Traditional Chinese and 6% in Simplified Chinese. Ordinary facts about other countries, such as "Japan is a country", do not change this way, and a general chat model used as a control (Claude Haiku) barely moves. Three of the four models also put the chance that "Taiwan is a country" is true at 11% or less, in every language, when no extra instructions are given.

**Why it matters.** The judgement is buried in software. The same model can treat a user writing in Traditional Chinese differently from one writing in Simplified Chinese, and neither will see it. Anyone using these models on content about Taiwan should test them in Traditional Chinese, Simplified Chinese and English.

---

*Decision models* return probabilities over predefined answers instead of generated text, and are sold for classification, routing and moderation. We tested four of them on statements about Taiwan's status:

- OpenAI **Decisions API** (`gpt-6-luna`)
- TypeSafe **Jev** (`jev-1.13.0`)
- Cloudflare **Clef** (27B) and **Clef-flash** (9B), open weights
- with **Claude Haiku 5.5** as a general-purpose LLM control

We rewrote 14 questions from the [Taiwan Sovereignty Benchmark](https://github.com/hsiaoa/ai-taiwan-sovereignty-benchmark) as 28 paired statements: one aligned with Taiwan's self-governance, one with the position of the People's Republic of China (PRC). Each statement was asked in Traditional Chinese, Simplified Chinese and English, under three phrasings and three personas, three times each: 18,225 runs in total, on 8 October 2026.

Simplified versions are machine-converted character by character from the Traditional versions, so the two differ **only in script**.

## Main results

| Model | Index S, Traditional | Index S, Simplified | Index S, English | Traditional − Simplified [95% item-bootstrap interval] |
|---|---|---|---|---|
| Decisions API | 0.85 | 0.68 | 0.84 | 0.16 [0.04, 0.32] |
| Jev | 0.11 | −0.16 | 0.07 | 0.27 [0.17, 0.40] |
| Clef (27B) | 0.15 | −0.32 | −0.10 | 0.47 [0.17, 0.76] |
| Clef-flash (9B) | −0.11 | −0.46 | −0.23 | 0.35 [0.21, 0.51] |
| Haiku 5.5 (control) | 0.58 | 0.56 | 0.56 | 0.05 [0.00, 0.08] |

Index S is the mean over pairs of P(self-governance-aligned statement) − P(PRC-position statement): +1 consistently aligned with Taiwan's self-governance, −1 consistently aligned with the PRC position. No persona; mean over phrasings and repetitions.

- **All four decision models move toward the PRC position when the same statement is written in Simplified characters.** The control moves by 0.05.
- Example (Clef): "Taiwan is not under the jurisdiction of the PRC" → 0.95 Traditional, 0.06 Simplified, 0.03 English.
- Without a persona, **Jev, Clef and Clef-flash never assign more than 0.11 to "Taiwan is a country"**, in any language or phrasing.
- On five neutral control pairs about other countries, no model showed a material script difference.
- On non-Taiwan topics sensitive for the PRC government, the Decisions API shows no script difference; Clef shows one on the Xinjiang statement.
- The Decisions API, Clef and Clef-flash returned identical probabilities in all three observed repetitions of every answered query.
- In a moderation task, no model assigned more than 0.5 to removing or escalating Taiwanese identity posts.

See the [paper](paper/main.pdf) for all experiments (E1–E6), limitations and discussion.

## Repository layout

| Path | Contents |
|---|---|
| `statements.json` | The 28 base statements (Traditional Chinese and English) |
| `build_jobs.py` → `jobs.jsonl`, `jobs.sha256` | All 1,215 jobs per model; Simplified text generated with OpenCC and checked character by character |
| `run.py` | API runner (3 repetitions; stores complete raw responses, HTTP counts and timestamps) |
| `results/*.jsonl` | Raw results for all five models (18,225 records) |
| `analyze.py` → `analysis/tables.md`, `figures/` | All tables and figures in the paper (deterministic bootstrap) |
| `paper_numbers.py` | In-text numbers not in the main tables |
| `verify_refs.py` → `analysis/ref-check.md` | Keyword checks of cited factual claims against their sources |
| `test_analyze.py` | Unit test for missing-answer handling |
| `paper/` | LaTeX source and PDF, English and Traditional Chinese |
| `reviews/` | Three rounds of adversarial review (OpenAI Codex) and the translation review |
| `pilot-v2/` | An earlier pilot with a weaker design, kept for transparency |
| `images/` | Images used in experiment E6, with credits |

## Reproduce

```bash
pip install -r requirements.txt
python build_jobs.py            # regenerates jobs.jsonl; hash must match jobs.sha256
python analyze.py               # regenerates analysis/ and figures/ from results/
python test_analyze.py
```

To re-run the models, put `OPENAI_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY`, `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in a `.env` file next to `run.py`, then `python run.py luna jev clef clef-flash haiku`. A full run cost under US$1 in October 2026. Models change; a new run describes the models at that time.

The Chinese PDF uses Noto Serif TC and Noto Sans TC (SIL Open Font License). Download them into `paper/fonts/` before compiling `main_zh.tex` with XeLaTeX or Tectonic.

## Citation

See `CITATION.cff`.

## Licence

Code: MIT. Data, results, figures and paper text: CC BY 4.0. The statements are adapted from the Taiwan Sovereignty Benchmark (MIT); see `THIRD_PARTY_NOTICES.md`. Image credits are in `images/CREDITS.md`.

## Contributors

- **Shang Nung Hsiao** (author): directed the study, approved its scope, design changes and publication, and is responsible for the content.
- **Claude** (Anthropic, Claude Opus 5.5 in Claude Code): experiment design, data-collection and analysis code, analysis, English draft and Traditional Chinese translation.
- **Codex** (OpenAI, `gpt-5.6-sol` via the Codex CLI): three rounds of adversarial review of the paper, data and code, and review of the Chinese translation (see `reviews/`).

Following arXiv policy, the AI tools are not listed as paper authors. Both tools come from vendors whose models are evaluated here: Claude Haiku 5.5 (Anthropic) is the control model and the Decisions API (OpenAI) is one of the models tested.

## Acknowledgements

This work extends the [Taiwan Sovereignty Benchmark](https://github.com/hsiaoa/ai-taiwan-sovereignty-benchmark) by hsiaoa, and builds on Ko (2026), [arXiv:2602.06371](https://arxiv.org/abs/2602.06371).
