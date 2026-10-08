# (A) Verdict

**Yes, once the repository URL is filled, the paper is ready for arXiv as a descriptive audit, with the minor wording and robustness fixes below strongly recommended before upload.** I found no BLOCKER or MAJOR issue in Round 3. The revised manuscript now discloses run- and cell-level missingness, performs the stated repetition-level sensitivity calculation on the present data, uses deterministic bootstrap intervals, represents Jev's English E5 result as a tie, narrows the E2--E4 and repeatability claims, and visually compiles cleanly in the supplied 11-page PDF. The remaining issues do not change the reported results: the abstract still states the neutral-control null too categorically, the manuscript does not show E2 effective sample sizes, two short result summaries remain broader than their small item sets, the reference-log description is stronger than the checker actually supports, and `p_imp` is not defensive against a future repetition whose entire result record is absent. The current dataset has no such absent non-skipped run, so that code issue does not affect any number in this paper.

# (B) Round-2 resolution table

## Items marked PARTLY in Round 2 section (B)

| Round-2 item | Status | Evidence |
|---:|:---:|---|
| B1 | RESOLVED | The abstract, Introduction and Discussion now restrict repeatability to the three observed repetitions (`main.tex:23,32,222`) and no longer say “every call.” |
| B5 | RESOLVED | Table 1 reports 18 wholly missing Haiku cells, 127 missing runs and 54 partly missing cells; `analyze.py:74-76,143-146` imputes unusable received repetitions before averaging. |
| B7 | RESOLVED | `main.tex:73` defines the intervals only as item-resampling descriptive intervals, while `analyze.py:111-118` derives a local seed from the values so a repeated statistic now has identical endpoints. |
| B8 | RESOLVED | `main.tex:185` removes the “in general” inference, confines the comparison to within-model differences, and explicitly states Haiku's non-equivalent message placement and separate self-reported calls. |
| B9 | RESOLVED | E4 is now “script and terminology”; `main.tex:81` calls the manipulation an unvalidated terminology-and-framing package, and `main.tex:189` limits the conclusion to the six authored pairs. |
| B10 | RESOLVED | `main.tex:65` explicitly reports the remaining delivery difference: prefix in the decision-model input versus system prompt for Haiku; no cross-channel persona effect is treated as calibrated. |
| B11 | RESOLVED | `main.tex:214` reports the Jev ordering association and English tie; `analyze.py:97-103,441-454` preserves ties and emits choices for every ordering. |
| B12 | PARTLY | `main.tex:168-172` is now appropriately limited to the tested controls, but the abstract still says neutral discrimination “does not depend on script,” which overstates five near-ceiling pairs. |
| B15 | RESOLVED | `verify_refs.py:1-2,52-60` now uses official OHCHR/PCA sources, states the limits of regex checking, verifies the PoPETs DOI, and adds the NCCU source. |
| B17 | NOT RESOLVED | This is the intentional pre-submission item specified by the author; see section (D). |
| B20 | PARTLY | `analysis/tables.md` contains the full E2 matrix, but the manuscript still gives selected item values and group summaries without per-group effective (n) after pairwise deletion or a compact appendix table. |
| B21 | RESOLVED | Figure 3 remains descriptive and `main.tex:185` explicitly compares magnitudes only within each model rather than making a cross-model causal inference. |
| B22 | PARTLY | Most vague/causal phrases were removed, but the abstract's categorical neutral-control null and the E6 sentence “We found no script difference for images” remain broader than the small purposive sets establish. |

## Findings from Round 2 section (C)

| Round-2 finding | Status | Evidence |
|---:|:---:|---|
| C1 | RESOLVED | `_SENTENCE` is absent from both `main.tex` and the compiled PDF; the Repeatability paragraph is complete at `main.tex:111`. |
| C2 | NOT RESOLVED | This is intentionally deferred; see section (D), and it is not counted as a Round-3 finding. |
| C3 | RESOLVED | `modal()` returns a sorted `tie:` label (`analyze.py:97-103`), the generated E5 table reports `tie:province/undetermined`, and `main.tex:214` reports the ordering association and 9-to-9 split. |
| C4 | RESOLVED | The paper reports wholly and partly missing cells and missing runs (`main.tex:94-111`); `p_imp` imputes each unusable received repetition, and the sensitivity results reproduce on the present complete set of run records. |
| C5 | RESOLVED | The timeless “fixed property/every call” wording is gone; the abstract and Discussion say “all three observed repetitions” (`main.tex:23,222`). |
| C6 | RESOLVED | `main.tex:185` no longer infers general political salience and discloses the Haiku/decision-model channel mismatch. |
| C7 | PARTLY | The Results section is properly qualified (`main.tex:168-172`), but the abstract still turns the neutral-control observation into the categorical statement that discrimination “does not depend on script.” |
| C8 | RESOLVED | E4 is expressly an author-created terminology/framing package without independent validation, and its conclusion is limited to the six tested pairs (`main.tex:81,187-206`). |
| C9 | RESOLVED | The neutral and disputed bounds are now “about” 0.01 and 0.09, and the Decisions comparison-president bound is correctly 0.02 (`main.tex:168,172,183`). |
| C10 | RESOLVED | Bootstrap seeding is local and data-derived (`analyze.py:111-118`); every repeated Table 2 statistic now has the same interval wherever printed. |
| C11 | PARTLY | Official sources and DOI/NCCU checks were added, but `main.tex:241` says the log “checks each external claim,” while `verify_refs.py:1-2` correctly admits that keyword presence does not verify the paper's overall synthesis. |
| C12 | RESOLVED | E3 now precedes E4, the unclear phrases were rewritten, and `requirements.txt` pins Python plus all imported third-party packages. |

# (C) Remaining findings table

There are **no BLOCKER or MAJOR findings**.

| # | Severity | Location | Issue | Evidence | Suggested fix |
|---:|:---:|---|---|---|---|
| 1 | MINOR | Abstract, `main.tex:23`; Results, `main.tex:168` | The abstract states a categorical null for neutral controls that the Results section correctly declines to generalise. | The largest exact neutral group Traditional-minus-Simplified gap is 0.01156 (Jev), but the five neutral pairs are near ceiling and are neither difficulty-matched nor large enough to establish script independence. | Replace “discrimination ... does not depend on script for any model” with “we observed no material script difference on five near-ceiling neutral control pairs.” |
| 2 | MINOR | `analyze.py:63-76,88-93,143-146` | Repetition-level imputation is correct for this dataset but does not impute a repetition whose whole run/answer record is absent. | `p_imp` averages only over `lst`; if `n_reps=2` because the third record is absent, the denominator remains 2. In contrast, the run-level counter correctly adds `3 - n_reps`. All five current files contain 3,645 run records, zero transport-error runs, and an answer object for every non-skipped run, so no reported value is affected. | Construct the expected three repetition slots per job/question and compute `p_imp = (sum(valid p) + 0.5 * missing_runs) / 3`; make `mixed_missing` and E5 missing counts use the same expected-slot logic. Add a unit test with one entirely absent repetition. |
| 3 | MINOR | Table 1 header/caption; `main.tex:111`; `analyze.py:79-93` | “Identical over 3 reps” and “every probability cell” obscure that Haiku's denominator includes cells with only two usable numeric replies. | The code counts any cell with `len(ps) >= 2`; 54 Haiku cells are partly missing (35 have two usable replies and 19 have one). The caption is more accurate than the header. | Rename the column “Identical among cells with ≥2 usable replies” and write “every answered probability cell” in the first sentence of Results. |
| 4 | MINOR | E2, `main.tex:159-172`; `analysis/tables.md:176-202` | Effective sample sizes after pairwise deletion are not visible in the manuscript. | Group sizes are stated as 5/4/3/2, but Haiku has three wholly missing E2 cells plus nine partly missing cells; readers cannot infer the effective paired (n) for each displayed group summary from the paper alone. | Add (n) to each E2 group estimate/caption or include the compact E2 group table in an appendix/supplement and point to it. |
| 5 | MINOR | E4, `main.tex:189,197-206` | “All differences are small” and “changed ... little” are undefined and sit awkwardly beside the acknowledged unvalidated framing packages. | Haiku's terminology estimate is 0.14 with interval ([-0.00, 0.38]), and the table header still says “TW terms/PRC terms” although the text calls them packages. | Use neutral numerical wording (“estimated terminology effects ranged from -0.07 to 0.14”) and relabel the headers “TW package/PRC package.” |
| 6 | MINOR | E6, `main.tex:218` | “We found no script difference for images” is broader than a five-image descriptive check with no defined image-level script statistic. | The five images show no consistent analogue of E1, but individual probabilities still vary by script (for example, Clef's Presidential Office state-symbol probability is 0.87/0.90/0.64). | Write “Across these five images we found no consistent E1-like script pattern.” |
| 7 | MINOR | Data and code availability, `main.tex:241`; `verify_refs.py:1-2` | The manuscript overstates what the automated reference log establishes. | The checker itself says regex presence does not validate the overall synthesis; for example, the NCCU check matches the page title, while the exact six-category detail requires reading the methodology. | Replace “checks each external claim” with “records source-level keyword checks for cited factual claims; broader syntheses were reviewed manually.” |

# (D) Pending before submission

- Replace `\url{REPO_URL}` with the public, preferably versioned repository/archive URL, then recompile once and verify the link in the PDF. The repository should contain the stimuli, canonical job file and hash, all raw JSONL responses, runner and analysis code, pinned requirements, generated tables/figures, reference log, and the disclosed pilot/reviews.

# (E) Numbers verified

I recomputed these values from `results/*.jsonl` by importing the analysis functions without executing the file-writing `__main__` path; no repository file was regenerated.

## Values changed in this revision

- **Table 1 missingness.** Decisions: 35 wholly missing cells = E1 32 + E2 1 + E3 2; all are missing in three repetitions, giving **35 / 105** cells/runs. Haiku: 18 wholly missing cells = E1 15 + E2 3; missing runs are E1 104 + E2 21 + E4 2 = **18 / 127** cells/runs.
- **Partly missing Haiku cells.** **54 total = 43 E1 + 9 E2 + 2 E4**. Of these, 19 have one usable numeric repetition and 35 have two; together with 18 fully missing cells this gives (19\times2 + 35\times1 + 18\times3 = 127) unusable question-repetition answers.
- **Table 2 intervals (Traditional-minus-Simplified; English-minus-Simplified).** Decisions **0.16 [0.04, 0.32]; 0.15 [0.05, 0.27]**. Jev **0.27 [0.17, 0.40]; 0.23 [0.16, 0.29]**. Clef **0.47 [0.17, 0.76]; 0.23 [0.01, 0.46]**. Clef-flash **0.35 [0.21, 0.51]; 0.23 [0.11, 0.36]**. Haiku **0.05 [0.00, 0.08]; 0.01 [-0.08, 0.11]**. Repeated E1 rows in the E2 output now reproduce these endpoints exactly.
- **Table 3 Clef-flash.** Script effect **0.01 [-0.02, 0.03]**; terminology effect **0.00 [-0.13, 0.17]**. The changed upper endpoint 0.17 reproduces with the deterministic bootstrap.
- **E5 Jev ordering.** Traditional: `210` gives province 3/3; `021` gives province/undetermined/undetermined; the other four orderings give undetermined 3/3, for **14 undetermined vs 4 province** overall. Simplified is province **18/18**. English: `201` and `210` give province 3/3; `021` and `120` give undetermined 3/3; `012` gives 2 province/1 undetermined and `102` gives 1 province/2 undetermined, for exactly **9 province to 9 undetermined**. The new `tie:province/undetermined` output is correct.
- **Comparison-president bound.** For the Decisions API, the twelve removal cells for South Korea, the Philippines, Chile and Poland have maximum **0.02** (not 0.01); the four Simplified values are 0.01, 0.02, 0.02 and 0.01, and all Traditional/English values are 0.01 or lower.
- **Sensitivity analysis.** Original versus all-unusable-repetitions-as-0.5 Traditional-minus-Simplified gaps are: Decisions 0.16095 → 0.17524 (change **0.01429**, hence “at most 0.02”); Jev 0.27032 → 0.27032; Clef 0.46790 → 0.46790; Clef-flash 0.35494 → 0.35494; Haiku 0.04671 → 0.05333, which is **0.05 after rounding in both analyses**. The manuscript sentence is correct.

## Five additional spot-checks

1. **Design/traffic:** 1,215 jobs per model, 3,645 runs per model, **18,225 runs** and **18,515 HTTP requests** total; zero transport-error runs.
2. **“Taiwan is a country”:** the no-persona maximum across Jev/Clef/Clef-flash, all three languages and phrasings, is **0.110** (Jev); Clef's maximum is 0.0797 and Clef-flash's is 0.0349.
3. **E3 Clef-flash removal:** the four Taiwan posts span **0.0971--0.3611** (mean 0.2142); the three analogs span **0.0178--0.0916** (mean 0.0588); the pro-unification post spans **0.1092--0.1219**.
4. **E3 clear violations:** the minimum, across models, of the two per-post language means is **0.9111** (Jev), supporting “at least 0.91.”
5. **E6 ROC flag state-symbol probability:** Decisions 1.00; Clef **0.9807--0.9912**; Clef-flash **0.8395--0.9195**; Haiku **0.95--1.00**, matching the rounded ranges in the paper.

## Code-path and external-claim checks

- `p_imp` correctly imputes unusable answer objects before cell averaging for the current data; the absent-record edge case is remaining finding #2 above.
- Bootstrap seeds are local SHA-256-derived seeds, so duplicate statistics are reproducible and independent of call order.
- `modal()` returns an explicit sorted tie, not first-seen `Counter.most_common(1)` output.
- Run-level missing counts correctly include both unusable answer objects and `3 - n_reps`; current Table 1 totals reproduce.
- The per-ordering E5 table enumerates all six orderings and exposes the two mixed Jev orderings in each affected language.
- Primary-source spot checks corroborate the [OpenAI Decisions API beta/model/predicate description](https://developers.openai.com/api/docs/guides/decisions), [Cloudflare Clef 27B documentation](https://developers.cloudflare.com/workers-ai/models/clef/), [Cloudflare Clef-flash 9B multimodal documentation](https://developers.cloudflare.com/workers-ai/models/clef-flash/), [TypeSafe Jev announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev), and the NCCU methodology's six substantive unification--independence options. I found no remaining external factual contradiction.
