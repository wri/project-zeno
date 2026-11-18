# BENCHMARK 2026-draft-5: concise profile with curated charts (2026-11-17)

> **Update, later on 2026-11-17.** After the changes in "Changes after the run", a full run on `0cf9eed5` gives a North Star of **78.4% (211 of 269)**, the same as prod. With the context layer rule, a full run on `3a9075df` gives **81.4% (219 of 269)** and 69.9% right every time (prod 78.4% and 65.1%). On 2026-11-18, a full run on `424c04e2` (the rule keeps the layer for "deforestation") gives **80.7% (217 of 269)** and 69.9% right every time. With DeepSeek V4.1 Flash in place of Gemini Flash, the North Star is the same (80.7%), the median latency is about 10 s more (27.0 s against 16.6 s), and the cost for each question is less than half (all DeepSeek calls $0.0048, the Gemini orchestrator calls only $0.0093; the code executor is Gemini in both). Later on 2026-11-18, a full run on `e67403c4` (the code review fixes, with the concise behavior as the default) gives the same North Star, **80.7% (217 of 269)**, and 70.6% right every time; the median latency is 24.8 s. See "Full run on `0cf9eed5`", "Full run on `3a9075df`", "Full run on `424c04e2`", "Full run on `e67403c4` (review fixes)" and "DeepSeek V4.1 Flash in place of Gemini Flash". The sections below those are about the first run.

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

## Changes after the run (`0cf9eed5`)

The lost questions are the part to fix. If the 23 lost questions passed as on prod and the 18 gains stayed, the North Star would be 229 of 269 (85.1%). That is an upper bound: prod also has questions that pass by chance. About 13 of the 23 losses come from the agent: caveats left out (4), stops at the dataset choice (6) and fire questions on the drivers dataset (3). Fixing these gives about 219 of 269 (81%).

Three changes, all for the concise profile only:

1. **The dataset selection reads the user's message.** The orchestrator never passed the user's words to `pick_dataset` (0 of 674 calls). It wrote a dataset phrase, for example "tree cover loss by driver (fire)" for "Has fire-driven tree cover loss in Bolivia gone down since the 2019 fire season?". The selection then offered a choice. Now `pick_dataset` gives the selection the user's latest message first, and the orchestrator's query as context for earlier turns. Retrieval uses the user's message.
2. **A part that no dataset gives does not stop the selection.** With the user's whole message, the rule "only choose a dataset if it can answer ALL parts" made the selection decline "why" questions and questions with a purpose ("We need it for NDC tracking"). With the user's message, the rule now says that the agent explains such a part, and the selection picks the data.
3. **Reply length by kind of turn, and new caution triggers.** One or two sentences for a selection only. One line for each option. Up to about 200 words after an analysis: the figures, what they mean for the question, then the cautions. As long as needed when the user asks for detail. New caution triggers: the user says what the figures are for (NDC or inventory tracking, verification, payments, compliance), or asks about a cause, a commodity or a boundary that the data does not identify.

### Offline selection test

The selection only, on the 48 questions where the run offered a choice and the question expects a dataset (one call each, two repetitions):

| Selection input | Expected dataset picked | Wrong dataset picked |
|---|---|---|
| The orchestrator's query (as in the run) | 1 of 41 (first test set) | 0 |
| User's message, query as context | 21 of 48 | 0 |
| The same, with the new rule | 25 to 26 of 48 | 0 |

All six fire questions pick tree cover loss due to fires on each call. Before, the selection offered drivers or fires. For 14 questions that expect no dataset, the new rule picks a dataset for 2 more (`ch-quant-187` social forestry, `ch-quant-184` production forest). The new caution trigger for an area with no defined boundary must cover these.

### Rerun of the 41 changed questions

The 23 lost and 18 gained questions, 3 attempts each, on `0cf9eed5`:

| | Full run | Rerun |
|---|---|---|
| Lost questions that pass | 0 of 23 | 15 of 23 |
| Gained questions that pass | 18 of 18 | 13 of 18 |
| Total | 18 of 41 | 28 of 41 |

Back: the caveat questions `ch-causal-018`, `ch-causal-026` and `ch-comp-173`; the fire questions `ch-quant-011` and `ch-causal-003`; the dataset-choice questions `ch-comp-093`, `ch-quant-133` and `ch-comp-152`; the "why" question `ch-causal-010`; and `ch-aoi-118`, `ch-causal-025`, `ch-comp-163`, `ch-mon-030`, `ch-quant-162` and `ch-trend-067`.

Still failing: `ch-quant-169` (the selection adds a context layer), `ch-port-018` (context layer), `ch-quant-153` (needs two datasets), `ch-comp-031`, `ch-comp-157`, `ch-port-003`, `ch-trend-037` and `ch-trend-080` (right on 1 of 3). Gains lost again: `ch-mon-035` (`pick_aoi` does not find the Wampis territory), `ch-causal-012` (answers from the WRI posts without a pull), `ch-quant-166`, `ch-quant-172` and `ch-quant-199`.

With the other 228 questions as in the full run, the estimate was about 216 of 269 (80.3%). The full run on `0cf9eed5` gave 211 of 269 (see "Full run on `0cf9eed5`").

## Full run on `0cf9eed5`

The same set, 3 attempts, local, `ff=concise`, with the fixed `chart_well_formed` check from the start (no rescore).

| | Prod baseline | First run | `0cf9eed5` |
|---|---|---|---|
| **North Star** | **78.4%** (211) | 76.6% (206) | **78.4%** (211; Wilson 95% CI 73.1 to 82.9%) |
| Right every time | 65.1% | 60.6% | 66.2% |
| Right at least once | 86.2% | 85.9% | 84.0% |
| Consistency | 175 of 211 | 163 of 206 | 178 of 211 |
| Failure modes (scope, retrieval, analysis, explanation) | 2, 31, 7, 18 | 1, 31, 7, 24 | 0, 27, 10, 21 |

| Type | Prod | First run | `0cf9eed5` |
|---|---|---|---|
| Quantification | 70 of 84 | 73 | 65 |
| Comparison | 46 of 57 | 46 | 50 |
| Monitoring | 30 of 41 | 31 | 33 |
| Causal | 20 of 31 | 14 | 17 |
| Trend | 20 of 23 | 18 | 21 |
| Refusal | 5 of 9 | 5 | 6 |
| Geospatial | 8 of 9 | 8 | 8 |
| Portfolio | 6 of 9 | 5 | 5 |
| Dataset | 6 of 6 | 6 | 6 |

Against prod, 20 questions gained and 20 lost (McNemar p = 1.0). Against the first run, 19 gained and 14 lost (p = 0.49). The estimate of 80.3% from the rerun of 41 questions did not hold: the other questions changed too.

**Unasked primary forest.** Of the 14 questions lost against the first run, 5 (`ch-quant-151`, `ch-quant-165`, `ch-quant-166`, `ch-quant-174`, `ch-quant-177`) pulled tree cover loss with the primary forest layer for a plain "tree cover loss" question. The selection gave the reason: primary forest is "the default for general forest loss requests" in the humid tropics. This default is in the tree cover loss selection hints and occurs on prod too, but less: unasked primary forest in 19 tree cover loss attempts on prod, 13 in the first run and 45 in this run.

Offline, on 37 plain tree cover loss questions (2 calls each):

| Selection input | Primary forest added |
|---|---|
| Orchestrator's query (first run) | 27 of 74 |
| User's message (`0cf9eed5`) | 25 of 74 |
| User's message and a rule: a layer only when the request names one (`3a9075df`) | 3 of 74 |

So the user's message does not cause the default. The live difference also has run-to-run variance. `3a9075df` adds the rule for the concise profile. Natural forest stays on EUDR and sourcing questions after 2020, where it is the layer that the regulation uses.

**Other losses against the first run:** `ch-causal-012` and `ch-causal-017` stop at a dataset choice; `ch-quant-172` answers from WRI posts without a pull; `ch-mon-035` (`pick_aoi` does not find the Wampis territory); `ch-quant-033` (period); `ch-comp-162` (figure); `ch-port-011`, `ch-quant-186` and `ch-quant-199` (text, 1 of 3).

## Full run on `3a9075df`

The same set, 3 attempts, local, `ff=concise`. The only change from `0cf9eed5` is the context layer rule.

| | Prod baseline | `0cf9eed5` | `3a9075df` |
|---|---|---|---|
| **North Star** | 78.4% (211) | 78.4% (211) | **81.4%** (219; Wilson 95% CI 76.3 to 85.6%) |
| Right every time | 65.1% | 66.2% | **69.9%** |
| Right at least once | 86.2% | 84.0% | 87.7% |
| Consistency | 175 of 211 | 178 of 211 | 188 of 219 |
| Failure modes (scope, retrieval, analysis, explanation) | 2, 31, 7, 18 | 0, 27, 10, 21 | 0, 22, 9, 19 |
| Attempts with no reply | 1 of 807 | 2 of 807 | 7 of 807 |

| Type | Prod | `0cf9eed5` | `3a9075df` |
|---|---|---|---|
| Quantification | 70 of 84 | 65 | 71 |
| Comparison | 46 of 57 | 50 | 50 |
| Monitoring | 30 of 41 | 33 | 32 |
| Causal | 20 of 31 | 17 | 18 |
| Trend | 20 of 23 | 21 | 21 |
| Refusal | 5 of 9 | 6 | 7 |
| Geospatial | 8 of 9 | 8 | 8 |
| Portfolio | 6 of 9 | 5 | 6 |
| Dataset | 6 of 6 | 6 | 6 |

Against prod, 23 questions gained and 15 lost (McNemar p = 0.26). Against `0cf9eed5`, 17 gained and 9 lost (p = 0.17). The North Star is 8 questions higher than prod, but the difference is not significant at this sample size.

**Context layer.** Tree cover loss pulls with the primary forest layer (asked and unasked) went from 77 of 159 to 33 of 159. Quantification went back from 65 to 71. Five gained questions had failed on `context_layer_match` before (`ch-quant-011`, `ch-quant-151`, `ch-quant-165`, `ch-quant-169`, `ch-quant-177`).

**One side effect.** `ch-quant-009` ("How much deforestation occurred in Brazil in 2023?") was right 3 of 3 and is now wrong 3 of 3. The benchmark expects the primary or the natural forest layer for "deforestation". With the rule, the selection gives no layer. The next commit corrects this: the rule now keeps the layer of the dataset hints for "deforestation", and a plain "tree cover loss" or "forest loss" request still gets no layer. Offline, with the orchestrator's query as context (3 queries, 4 calls each), the old rule gave no layer for this question in 12 of 12 calls, and the new rule gave primary forest in 12 of 12. On the 52 tree cover loss questions of the BENCHMARK (2 calls each, user's message only), the new rule matched the expected layer in 60 of 62 checked calls, against 58 of 62 for the old rule, and added primary forest to no question that expects no layer. The full run on `424c04e2` is in the next section.

**No reply.** 5 of the 7 attempts with no reply stop after a standard chart, with no final message. Two of them are `ch-quant-009` (about 220 s each). `0cf9eed5` had 5 such attempts too, so this is not from the rule.

**Other losses against `0cf9eed5`:** figures in `ch-mon-030`, `ch-comp-150` and `ch-comp-163`; no pull in `ch-mon-056` and `ch-mon-058`; text in `ch-trend-053` and `ch-causal-026`; the area in `ch-quant-182`. Each of these was right on 1 or 2 attempts in one of the two runs. `ch-mon-035` (Wampis territory) passes now on 3 of 3.

**Latency.** The median attempt took 33.4 s, against 17.8 s on `0cf9eed5`. The tool calls are the same (3.3 per attempt, the same mix of standard and CodeAct charts). The slow attempts are all in the first third of the run (median 65.8 s, against 31.1 s for the same questions on `0cf9eed5`). The last two thirds are equal to `0cf9eed5`. So the cause is not in the code; the model API was slower during that hour. Do not use this run for latency.

## Full run on `424c04e2`

2026-11-18. The same set, 3 attempts, local, `ff=concise`. The only change from `3a9075df` is that the layer rule keeps the layer of the dataset hints for "deforestation".

| | Prod baseline | `3a9075df` | `424c04e2` |
|---|---|---|---|
| **North Star** | 78.4% (211) | 81.4% (219) | **80.7%** (217; Wilson 95% CI 75.5 to 84.9%) |
| Right every time | 65.1% | 69.9% | 69.9% |
| Right at least once | 86.2% | 87.7% | 88.1% |
| Consistency | 175 of 211 | 188 of 219 | 188 of 217 |
| Failure modes (scope, retrieval, analysis, explanation) | 2, 31, 7, 18 | 0, 22, 9, 19 | 0, 27, 6, 19 |
| Attempts with no reply | 1 of 807 | 7 of 807 | 1 of 807 |

| Type | Prod | `3a9075df` | `424c04e2` |
|---|---|---|---|
| Quantification | 70 of 84 | 71 | 73 |
| Comparison | 46 of 57 | 50 | 49 |
| Monitoring | 30 of 41 | 32 | 30 |
| Causal | 20 of 31 | 18 | 19 |
| Trend | 20 of 23 | 21 | 21 |
| Refusal | 5 of 9 | 7 | 7 |
| Geospatial | 8 of 9 | 8 | 7 |
| Portfolio | 6 of 9 | 6 | 6 |
| Dataset | 6 of 6 | 6 | 5 |

Against prod, 22 questions gained and 16 lost (McNemar p = 0.42). The difference from `3a9075df` (2 questions) is in the run-to-run variance. A question-by-question comparison with `3a9075df` is not possible: a reboot deleted the files of that run.

**Deforestation.** `ch-quant-009` passes again on 3 of 3 attempts. The questions that the layer rule corrected stay correct: `ch-quant-011`, `ch-quant-151`, `ch-quant-165` and `ch-quant-169` on 3 of 3, `ch-quant-177` on 2 of 3. Tree cover loss pulls with the primary forest layer: 31 of 164 (33 of 159 on `3a9075df`, 77 of 159 on `0cf9eed5`).

**Lost against prod (16).** Most were right on 1 of 3 attempts:
- No pull: `ch-quant-153` (needs two datasets), `ch-causal-017` and `ch-causal-003` (stop at the dataset choice), `ch-comp-031`.
- Figures: `ch-mon-030`, `ch-comp-163`, `ch-causal-010`, `ch-quant-036`.
- Text: `ch-comp-157`, `ch-causal-018`, `ch-aoi-155`, `ch-trend-087`.
- Other: a chart in `ch-comp-158`, the period in `ch-port-018` and `ch-trend-083`, the dataset in `ch-dataset-157`.

**Latency.** This run had no slow period. Median 16.6 s and 90th percentile 51.6 s (`stream_s`, as in "Latency and cost"), against 31.2 s and 53.3 s on prod. The first third of the questions has a median of 37.4 s and the other two thirds 13.8 s, the same pattern as `0cf9eed5`. The same limits apply as before: a local API, and prod on a different build. 211 of 807 attempts used the code executor, and 264 got only standard charts. Cost was not measured.

## Full run on `e67403c4` (review fixes)

2026-11-18. The same set, 3 attempts, local, 10 workers, Gemini Flash. The concise behavior is now the default (`35b90681`), so the run uses `ff=curated-charts`. This gives the same configuration as `ff=concise` in the earlier runs. The changes from `424c04e2` are the fixes from the code review (`e67403c4`):

- The `generate_insights` message and the curated chart message have the dataset cautions again. The cautions come from the dataset in state, or else from the catalog.
- The `pick_dataset` message has the function usage notes again.
- The dataset retrieval uses the user's message and the agent's request. It takes the best results of each in turn, at most 5 datasets.
- When the user's message asks for more than one dataset, the selection selects the dataset for the part that the agent's request names.

| | Prod baseline | `424c04e2` | `e67403c4` |
|---|---|---|---|
| **North Star** | 78.4% (211) | 80.7% (217) | **80.7%** (217; Wilson 95% CI 75.5 to 84.9%) |
| Right every time | 65.1% | 69.9% | 70.6% |
| Right at least once | 86.2% | 88.1% | 88.8% |
| Consistency | 175 of 211 | 188 of 217 | 190 of 217 |
| Failure modes (scope, retrieval, analysis, explanation) | 2, 31, 7, 18 | 0, 27, 6, 19 | 0, 23, 9, 20 |
| Attempts with no reply | 1 of 807 | 1 of 807 | 1 of 807 |

| Type | Prod | `424c04e2` | `e67403c4` |
|---|---|---|---|
| Quantification | 70 of 84 | 73 | 68 |
| Comparison | 46 of 57 | 49 | 51 |
| Monitoring | 30 of 41 | 30 | 31 |
| Causal | 20 of 31 | 19 | 20 |
| Trend | 20 of 23 | 21 | 23 |
| Refusal | 5 of 9 | 7 | 6 |
| Geospatial | 8 of 9 | 7 | 8 |
| Portfolio | 6 of 9 | 6 | 6 |
| Dataset | 6 of 6 | 5 | 4 |

Against prod, 21 questions gained and 15 lost (McNemar p = 0.41). Against `424c04e2`, 12 gained and 12 lost (p = 1.0). The review fixes do not change the North Star. Retrieval failures decrease from 27 to 23. Analysis and explanation failures increase by 4 together. All differences are in the run-to-run variance.

**Gained against `424c04e2` (12):** `ch-aoi-155`, `ch-causal-003`, `ch-comp-031`, `ch-comp-157`, `ch-comp-158`, `ch-comp-176`, `ch-mon-030`, `ch-mon-056`, `ch-port-018`, `ch-quant-159`, `ch-trend-083`, `ch-trend-087`. Nine of them are in the 16 questions that `424c04e2` lost against prod. `ch-comp-031` and `ch-causal-003` stopped at the dataset choice before.

**Lost against `424c04e2` (12):** 9 of 12 were right on 1 of 3 attempts.
- Retrieval: `ch-dataset-171` ("Show me deforestation", the dataset on 1 of 3), `ch-port-003` (the AOI is Brazil, not its states, on 3 of 3), `ch-mon-032` and `ch-quant-186` (the AOI), `ch-quant-182`.
- Figures: `ch-comp-076`, `ch-quant-146`, a chart in `ch-quant-171`.
- Text: `ch-aoi-128` and `ch-quant-163` (raw coordinates: the agent moves the map or offers datasets), `ch-comp-181` (offers a dataset choice and does not explain the difference), `ch-quant-196` (gives a meaning to a pixel value that is not documented).

`ch-dataset-171` and `ch-comp-181` use `pick_dataset`, and the retrieval changed. Examine them before the release. The other losses are in tools that this change does not touch.

**Caveat questions.** Of the questions that failed for a missing caveat in the first run, `ch-causal-026` and `ch-comp-173` pass (2 of 3), and `ch-causal-018` fails on 3 of 3. The cautions in the tool messages do not decrease the explanation failures (20, against 19 on `424c04e2`).

**Latency.** Median 24.8 s and 90th percentile 65.8 s (`stream_s`), against 16.6 s and 51.6 s on `424c04e2`. The first third of the questions has a median of 46.2 s (38.1 s before), and the other two thirds 17.7 s and 18.0 s (13.6 s before). The API log has no rate limit errors. The cause is not known: the longer tool messages (cautions and usage notes) and the two retrievals add some time, but the analytics API and the Gemini API also change during the day. A run with Langfuse tracing is necessary to find the cause.

## DeepSeek V4.1 Flash in place of Gemini Flash

2026-11-18. The same set, 3 attempts, local, `ff=concise`, 10 workers, on `9b36fdc8` (the code of `3a9075df`). MODEL and SMALL_MODEL are `deepseek/deepseek-v4.1-flash` through OpenRouter, with no fallback models. CODING_MODEL stays on Gemini, because only the Gemini code executor has a sandbox. The OpenRouter backend is from `feat/openrouter-models` (`cadebdb6`) and is not in this PR. The run used gnw-gold-evals `main` (`e5937ae`) with the `chart_well_formed` fix. It ran in the same hour as the `424c04e2` run, on the same local database.

### Summary: cost and latency estimate for one question

| | Gemini Flash (`424c04e2`) | DeepSeek V4.1 Flash | Basis |
|---|---|---|---|
| North Star | 80.7% (217) | 80.7% (217) | measured |
| Latency, median | 16.6 s | 27.0 s | measured (`stream_s`, same hour) |
| Latency, 90th percentile | 51.6 s | 67.0 s | measured |
| Orchestrator cost | $0.0093 | $0.0015 to $0.0043 | thread state tokens × price; DeepSeek: range of provider prices, see below |
| Orchestrator and subagents | more than $0.0093 (subagents not measured) | **$0.0048** | DeepSeek: measured, OpenRouter key spend |
| For 1,000 questions | more than $9.30 | about $4.80 | |

The code executor (`generate_insights`) is Gemini in both runs and is not in these numbers.

**What the cost numbers can show.** The DeepSeek cost of all the orchestrator and subagent calls ($0.0048) is about half of the Gemini cost of the orchestrator calls only ($0.0093). So DeepSeek costs less than half of Gemini for the same questions. The full ratio is not known: the thread state does not record the subagent (SMALL_MODEL) calls, and Langfuse tracing was off. To measure it, run both models with Langfuse tracing on.

**DeepSeek price is not one value.** OpenRouter sends each request to one of 38 providers of `deepseek/deepseek-v4.1-flash`, at $0.051 to $0.45/M input and $0.34 to $1.80/M output, without the $3.00/$12.00 "ultrafast" provider. The run did not record which provider served each call. The key spend ($3.86) is what OpenRouter charged. The split of that spend between the orchestrator and the subagents is not known.

### Accuracy

| | `3a9075df` (Gemini) | `424c04e2` (Gemini) | `9b36fdc8` (DeepSeek) |
|---|---|---|---|
| **North Star** | 81.4% (219) | 80.7% (217) | **80.7%** (217) |
| Right every time | 69.9% | 69.9% | 69.1% |
| Right at least once | 87.7% | 88.1% | 88.5% |
| Consistency | 188 of 219 | 188 of 217 | 186 of 217 |
| Failure modes (scope, retrieval, analysis, explanation) | 0, 22, 9, 19 | 0, 27, 6, 19 | 1, 27, 8, 16 |
| Attempts with no reply | 7 of 807 | 1 of 807 | 2 of 807 |

| Type | Prod | `424c04e2` (Gemini) | DeepSeek |
|---|---|---|---|
| Quantification | 70 of 84 | 73 | 71 |
| Comparison | 46 of 57 | 49 | 51 |
| Monitoring | 30 of 41 | 30 | 31 |
| Causal | 20 of 31 | 19 | 18 |
| Trend | 20 of 23 | 21 | 20 |
| Refusal | 5 of 9 | 7 | 7 |
| Geospatial | 8 of 9 | 7 | 8 |
| Portfolio | 6 of 9 | 6 | 6 |
| Dataset | 6 of 6 | 5 | 5 |

Against `424c04e2`, DeepSeek gains 22 questions and loses 22 (McNemar p = 1.0). Against prod, it gains 28 and loses 22 (p = 0.48). The accuracy of the two models is the same at this sample size.

**Losses against `424c04e2` (22).** Most were right on 1 of 3 attempts. Some are not from the model:

- `ch-quant-009` (deforestation layer): the DeepSeek run does not have the `424c04e2` fix.
- Charts with mis-joined record sets (`chart_integrity`): `ch-comp-076` (3 of 3), `ch-quant-171`, `ch-trend-037`. The Gemini run does not show this failure. Examine the chart arguments that DeepSeek writes.
- Text: the alert questions `ch-mon-040`, `ch-mon-052` and `ch-mon-063` (the reply is correct but does not name the channel or ask which item), `ch-causal-026`, `ch-quant-176`, `ch-quant-185`, `ch-quant-163`.
- No pull or wrong area: `ch-mon-008`, `ch-quant-110`, `ch-comp-168`, `ch-comp-171`, `ch-causal-023`, `ch-trend-081` (154 protected areas in Madagascar).
- Figures: `ch-comp-161`, `ch-comp-173`, `ch-causal-024`, `ch-trend-052`.
- Scope: `ch-dataset-171` calls `search_blogs` on 3 of 3 attempts.

### Latency

| | `424c04e2` (Gemini, same hour) | DeepSeek |
|---|---|---|
| Median | 16.6 s | 27.0 s |
| 90th percentile | 51.6 s | 67.0 s |
| Mean | n/a | 36.8 s |

DeepSeek is about 10 s slower at the median. It writes about 2.5 times more output tokens than Gemini, and half of them are thinking tokens. The two runs used the same local database and analytics API at the same time, so the load on these was the same for both.

### Tokens and cost (orchestrator)

From the thread state of each attempt (the `usage_metadata` of each AI message), Gemini 3 Flash at $0.50/M input, $0.05/M cache read, $3.00/M output. DeepSeek V4.1 Flash at the lowest provider price ($0.051/M, $0.018/M, $0.567/M) to the price of most providers ($0.30/M, $0.03/M, $1.20/M). Medians for each attempt:

| | Gemini Flash (`0cf9eed5`, `3a9075df`, `424c04e2`) | DeepSeek V4.1 Flash |
|---|---|---|
| Model calls | 5 | 5 |
| Input, not cached | 14,400 | 5,500 |
| Input, cache read | 12,000 (45% of input) | 21,500 (74% of input) |
| Output | 380 to 400 | 1,012 (478 of them thinking) |
| All tokens | 28,300 | 32,200 |
| Cost for each attempt | $0.0093 | $0.0015 to $0.0043 |
| Cost for the run (807 attempts) | $7.36 to $8.53 | $1.17 to $3.45 |

DeepSeek uses about 14% more tokens, but the orchestrator cost is about 2 to 7 times less. Limits:

- The Gemini thread states record 0 thinking tokens. If Gemini bills thinking tokens that the state does not record, the Gemini cost is higher than the table shows.
- The OpenRouter key spend ($3.86) is the change in the key's usage during the run. Other use of the key in that hour would be in it.

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

## Latency and cost

**Latency.** The harness records the time of each attempt (`stream_s`: from the chat request to the last line of the stream). Both runs used 10 workers.

| | Prod baseline | This PR (`ff=concise`) |
|---|---|---|
| Median | 31.2 s | 15.3 s |
| 90th percentile | 53.3 s | 44.0 s |

The median is half of the baseline. This agrees with the curated path: no code executor call and a shorter tool message. But the comparison is not clean. The baseline ran on prod with the build of 2026-10-27. This run used a local API, with a different network, database and analytics API. Do not report the difference as a gain of this PR.

**Cost.** This run did not measure cost:

- The gnw-gold-evals ledger records no tokens. Only the `efficiency` object of `evals/gold` in this PR records them.
- Langfuse tracing was off for the local API, so the run has no traces.
- The local thread states give the orchestrator tokens, but not the tokens of the subagents and the code executor. Those model calls are not in the thread state. Curated charts should save most in the code executor: 279 of the 481 attempts that called `generate_insights` did not call it.

**To measure the gain:** run the default profile and `ff=concise` on the same build at the same time, on a local API with local Langfuse tracing on. Then compare the latency and the tokens of all model calls, including the subagents and the code executor, with the price of each model.

## Recommendations

1. **Caveats.** Decide which caveats a short reply must keep. The four lost questions want a caveat about the use of the figures (NDC tracking, results verification) or about what the data cannot show (commodities, a boundary that is not defined). Concise rule 7 gives a caveat only with a trigger word. These questions have no trigger word.
2. **Fire questions.** Examine why `pick_dataset` offers the drivers dataset, or the choice of two datasets, for "fire-driven loss" questions. Tree cover loss due to fires has the years these questions need.
3. **Dataset choice stops.** The increase (143 to 160 attempts) is small, but 6 lost questions come from it. A comparison run on the default profile with the same build would show if this PR causes it.
4. **Before release:** run the benchmark on the default profile and on `ff=concise` of the same build, with Langfuse tracing on. That separates the effect of this PR from the other changes since 2026-10-27, and it measures the latency and cost gain (see "Latency and cost").

## Files

The run file, the page data and the agent artifacts are local and not committed to gnw-gold-evals:

- Run: `20261117T142839Z_local_concise.json` (with `chart_well_formed` scored again; the file as the harness wrote it is kept as `.pre-rescore.json`).
- Page data: built with `tools/benchmark_page.py` from the same run.
- Run on `e67403c4`: `20261118T160513Z_local_curated-charts.json`, with its page data and agent artifacts, in `~/bench-runs/pr911/run-e67403c4/` on the machine that ran it.
