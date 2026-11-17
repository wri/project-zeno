# BENCHMARK 2026-draft-5: concise profile with curated charts (2026-11-17)

## Result

| | Prod baseline (default profile) | This PR (`ff=concise`) |
|---|---|---|
| **North Star** (right on most attempts) | **78.4%** (211 of 269; Wilson 95% CI 73.1 to 82.9%) | **76.6%** (206 of 269; Wilson 95% CI 71.2 to 81.2%) |
| Right every time | 65.1% | 60.6% |
| Right at least once | 86.2% | 85.9% |
| Consistency (right answers right on all 3 attempts) | 83% (175 of 211) | 79% (163 of 206) |
| Attempts with no reply | 1 of 807 | 2 of 807 |
| Errored questions | 0 | 0 |

The difference is not significant. 18 questions pass now and failed on prod. 23 questions failed now and passed on prod. An exact McNemar test on these 41 questions gives p = 0.53. The two confidence intervals overlap almost fully.

The failures moved between stages. Retrieval failures are the same (31). Explanation failures increased from 18 to 24. The main cause is that the short replies leave out caveats that some questions require (see "Lost questions").

## What ran

- **Agent:** `feat/concise-agent` at `9eb54f40`, local API, `ff=concise`. This commit adds curated charts first (#910) to the concise profile. So the run measures the two changes together: short replies and curated charts.
- **Set:** BENCHMARK `2026-draft-5`, 269 questions, 3 attempts each. The member uids are the same as in the baseline.
- **Harness:** gnw-gold-evals `fa337b5`. This is `main` (`e5937ae`) plus one fix to `chart_well_formed` (see "Check change").
- **Baseline:** the canonical prod page `20261028T124051Z_prod` (default profile, prod, 2026-10-27 and 2026-10-28).

### Differences from the baseline that are not from this PR

- The baseline ran on prod with the agent build of 2026-10-27. This run used a local API with the build of this PR. Other changes on `main` between the two dates are also in this run.
- Questions with a relative window (for example "the last month") ask for a different period on each date. The alerts data for that period is different too.
- The run is local and not canonical. It is not a trend point on the scorecards page.

## Check change

Before this run, `chart_well_formed` failed every curated integrated alerts chart. That chart has `yAxis: "area_ha"` as the axis title and one column for each confidence tier in `seriesFields`. The check looked for an `area_ha` column and did not find one. The fix (gnw-gold-evals `fa337b5`, not pushed yet) checks the `seriesFields` columns, and not the `yAxis`, when a chart has series.

The run stopped after 190 questions to add the fix. The last 79 questions ran with the fixed check. For the first 190 questions, a script scored `chart_well_formed` again for each attempt from its saved chart data, with the same majority rule as the harness. 49 attempts and 19 questions changed from fail to pass: 15 `ch-mon-*` questions, `ch-quant-080`, `ch-quant-082`, `ch-quant-083` and `ch-causal-019`. No attempt changed from pass to fail.

## By type

| Type | Prod | This PR | Change |
|---|---|---|---|
| Quantification | 70 of 84 (83%) | 73 of 84 (87%) | +3 |
| Comparison | 46 of 57 (81%) | 46 of 57 (81%) | 0 |
| Monitoring | 30 of 41 (73%) | 31 of 41 (76%) | +1 |
| Causal | 20 of 31 (65%) | 14 of 31 (45%) | **−6** |
| Trend | 20 of 23 (87%) | 18 of 23 (78%) | −2 |
| Geospatial | 8 of 9 | 8 of 9 | 0 |
| Refusal | 5 of 9 | 5 of 9 | 0 |
| Portfolio | 6 of 9 | 5 of 9 | −1 |
| Dataset | 6 of 6 | 6 of 6 | 0 |

Failure modes (first failing stage):

| Stage | Prod | This PR |
|---|---|---|
| Scope | 2 | 1 |
| Retrieval | 31 | 31 |
| Analysis | 7 | 7 |
| Explanation | 18 | 24 |

## Lost questions (23)

**Caveat left out (4).** The reply gives the figures but not the caveat that the question requires. These are the clearest effect of the short replies. The curated tool message also leaves out the dataset cautions with this flag.

- `ch-quant-169`: gives Colombia's 2023 emissions but does not say that the method differs from the national inventory for NDC tracking.
- `ch-comp-173`: does not describe the figures as an informal cross-check of Ghana's results report.
- `ch-causal-018`: names cocoa as a finding of the drivers data.
- `ch-causal-026`: gives national figures only, and does not say that the cocoa belt is not a defined boundary.

**Stopped at the dataset choice (6).** On most attempts, `pick_dataset` offered two datasets and the agent stopped to ask: `ch-quant-153`, `ch-comp-093`, `ch-comp-152`, `ch-quant-133`, `ch-comp-031`, `ch-port-003`. The prod run passed these questions on most attempts. In all attempts, a stop after `pick_dataset` occurred 160 times, against 143 on prod.

**Fire question answered from the drivers dataset (3).** For `ch-quant-011` and `ch-trend-080`, some attempts used tree cover loss by driver (no years) in place of loss due to fires, and then said that the data has no years. `ch-causal-003` used tree cover loss with primary forest in place of the fires dataset on all 3 attempts.

**Judge reason and score do not agree (3).** For `ch-causal-010`, `ch-causal-025` and `ch-port-018`, the judge's reason says that the reply meets the expectation, but the score is a fail. Examine these before you act on them.

**Other (7).**

- `ch-mon-030`, `ch-comp-163`: alerts questions with a relative window (the last month). The figure or the period did not match on 2 of 3 attempts. The data for that window is different from the baseline date.
- `ch-comp-157`: asked back on 2 attempts with an option that the question does not accept.
- `ch-trend-067`: wrong context layer on 2 of 3 attempts.
- `ch-trend-037`: a pie chart with null names on 2 of 3 attempts (`chart_integrity`).
- `ch-aoi-118` ("Show me the Cerrado"): resolved a municipality with "cerrado" in its name, and did not ask about the biome.
- `ch-quant-162`: right on 1 of 3 attempts; one attempt used the drivers dataset.

## Gained questions (18)

- **Retrieval failure on prod (8):** `ch-mon-035`, `ch-quant-172`, `ch-causal-012`, `ch-comp-053`, `ch-comp-171`, `ch-trend-081`, `ch-comp-090`, `ch-quant-199`.
- **Explanation (5):** `ch-port-001`, `ch-quant-166`, `ch-quant-170`, `ch-mon-045`, `ch-dataset-187`.
- **Analysis (4):** `ch-comp-038` and `ch-comp-076` (no null fields in the chart), `ch-comp-153` (period), `ch-quant-189` (figure).
- **Scope (1):** `ch-quant-175`.

## Curated charts

Of the 481 attempts that called `generate_insights`, 279 (58%) showed a curated chart. The agent set `chart="standard"` 211 times and `chart="custom"` 183 times, and did not set `chart` 105 times (the default is `standard`).

| View | Charts |
|---|---|
| `tcl.annual_loss` | 89 |
| `tcl.annual_emissions` | 86 |
| `integrated_alerts.by_confidence` | 60 |
| `tcl_by_driver.by_driver` | 42 |
| `grasslands.by_year` | 14 |
| `natural_lands.by_class` | 13 |
| `tree_cover_gain.by_period` | 12 |
| `tree_cover.extent` | 12 |
| `tcl_by_fires.annual_split` | 11 |
| `forest_flux.net` | 11 |
| `tcl_by_fires.split` | 9 |
| `land_cover.composition` | 6 |

Final replies: median 88 words, 90th percentile 120 words. The baseline page keeps only an excerpt of each reply, so this run has no word count to compare with.

## Recommendations

1. **Caveats.** Decide which caveats a short reply must keep. The four lost questions want a caveat about the use of the figures (NDC tracking, results verification) or about what the data cannot show (commodities, a boundary that is not defined). Concise rule 7 gives a caveat only with a trigger word. These questions have no trigger word.
2. **Fire questions.** Examine why `pick_dataset` offers the drivers dataset, or the choice of two datasets, for "fire-driven loss" questions. Tree cover loss due to fires has the years these questions need.
3. **Dataset choice stops.** The increase (143 to 160 attempts) is small, but 6 lost questions come from it. A comparison run on the default profile with the same build would show if this PR causes it.
4. **Before release:** run the benchmark on the default profile of the same build, or on prod after the merge. That separates the effect of this PR from the other changes since 2026-10-27.

## Files

The run file, the page data and the agent artifacts are local and not committed to gnw-gold-evals:

- Run: `20261117T142839Z_local_concise.json` (with `chart_well_formed` scored again; the file as the harness wrote it is kept as `.pre-rescore.json`).
- Page data: built with `tools/benchmark_page.py` from the same run.
