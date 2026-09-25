# jev for agent decisions: opportunity and first test

Status: exploring · Test: PR #841

## What jev is

jev is a "decision model" from Typesafe. It does not write text. You give it a situation and a question with a fixed set of options. It returns one option, a probability for each option and a confidence value. We tested two versions:

- `openjev-latest` (open model) on `api.codiv.ai`
- `typesafe/jev-1.13` on OpenRouter (`/api/alpha/decisions`)

## Opportunity

Some of our LLM calls are decisions, not text generation. For these calls, jev can be:

- **Faster:** 0.3–0.8 s for each call.
- **Cheaper:** approximately $0.00006 for each call with short descriptions.
- **Easier to control:** the answer is always one of the options, never an invented value. We also get probabilities, so we can see when the model is not sure.
- **No RAG step:** in the test, jev saw all datasets at once and did not need the RAG pre-filter. This removes the RAG and LLM pipeline from dataset selection.
- **No embeddings index to maintain:** without RAG, we do not have to version the index or keep it in sync with the catalog YAML.
- **A simpler catalog:** each dataset needs only a short description for selection. We can restructure the YAML around this and keep the long LLM text only where it is still used.

An LLM is still necessary for text, extraction (places, dates) and the orchestrator.

## Why we test on dataset selection

- It is a clear decision: one dataset out of 11, or none.
- We have labeled cases: the unit tests, the GOLD sheet and the eval CSVs.
- Errors are expensive: a wrong dataset gives a wrong answer.

## Other places where jev can help

| Place | Decision | Fit |
|---|---|---|
| `pick_dataset` | dataset, context layer, parameter | Tested |
| `pick_aoi` candidate selection | which geocoder result the user means | Good: fixed candidate list |
| `pick_aoi` extraction | area type, subregion type | Partial: the place names still need an LLM |
| Nudges and clarifications | ask the user or continue | Possible |
| Off-topic or guardrail checks | is the query in scope | Possible |
| Insight text, thread names, translations | text | No |

## Results

The dev set (89 queries) has many short, general queries. The two holdout sets (89 queries) have long, specific GOLD-style queries.

| | Open jev | OpenRouter jev |
|---|---|---|
| Current picker text, dev set | 78% | 84% |
| Current picker text, holdout sets | 83% | 96% |
| Short instruction and short descriptions, dev set | **94%** | **94%** |
| Short instruction and short descriptions, holdout sets | **94%** | **98%** |
| Time for each call | 0.8 s | 0.3 s |

What we learned:

- **jev needs its own instructions.** The LLM rules ("only choose a dataset if it answers ALL parts") make jev decline valid queries. One short sentence fixes this.
- **Short descriptions are sufficient.** They are 80% shorter than the catalog text and 3.5 times cheaper, with the same accuracy.
- **Declines are weak.** jev seldom selects "none" correctly (0–3 of 6 cases).

Details, method and raw results: PR #841 and `scripts/jev_experiments/`.

### End-to-end test: current picker and jev in the agent

The results above test jev alone. This test puts jev inside the real agent and compares it with the current picker (RAG and LLM) on the same prompts. It gives part of the answer to go / no-go step 1.

**Test setup**

- The prompts are 200 "show me X on the map" requests, in the gnw-gold-evals CHALLENGE `map` set. No prompt names a place or a date, so the agent only has to select a dataset.
- There are 3 trials for each prompt.
- The two runs used the same local stack: the same code, the same agent model (Gemini 3 Flash, the same as production), the same embeddings index (v10) and the same prompts. Only the picker was different:
  - **Current picker:** `DATASET_PICKER=rag`.
  - **jev:** `DATASET_PICKER=jev`, with `typesafe/jev-1.13` on OpenRouter. It used the short instruction and the short descriptions (`cards_neutral`) from the experiments above.
- jev sees all datasets in the profile. For datasets that have context layers or parameters (4, 6, 7, 8 and 10), a second jev call selects them. The second call offers only the options of the selected dataset.
- A prompt passes when the agent selects the expected dataset in at least 2 of the 3 trials. For the "ask" prompts, it passes when the agent offers the expected dataset choice. A prompt fails if the agent pulls data, makes a dashboard or searches the blogs.

**Results**

| | Current picker | jev |
|---|---|---|
| Pass rate | 87.5% (175 of 200) | **92.0% (184 of 200)** |
| Pass rate, all 3 trials correct | 81.0% | **88.0%** |
| Time to select a dataset, median / p90 | 2.25 s / 2.79 s | **0.50 s / 0.71 s** |
| Time for the agent turn, median / p90 | 8.4 s / 10.9 s | **6.6 s / 9.6 s** |
| Picker cost, 600 trials | not measured | **$0.044** |

| Prompt group | Prompts | Current picker | jev |
|---|---|---|---|
| One group for each mappable dataset (easy, medium, hard) | 130 | 88.5% | **94.6%** |
| Other languages (es, pt, fr, id, sw) | 25 | **100%** | 92.0% |
| Context layer (primary forest, intact forest) | 15 | 93.3% | 93.3% |
| Ambiguous (more than one dataset can help) | 15 | 53.3% | **66.7%** |
| No map layer (sLUC, weather, species, soil) | 15 | 86.7% | **93.3%** |

**What we learned**

- **jev is faster.** Dataset selection is 4.5 times faster. The full agent turn is 1.8 s faster at the median, and it is faster in all prompt groups. jev takes approximately 0.3 s with one call and 0.6 s with the second call.
- **jev is as accurate as the current picker, or better.** The two pickers give different results on 21 prompts. The current picker fails 15 of them and jev fails 6. This is a strong trend, but it is not yet statistically significant (McNemar p ≈ 0.08).
- **The current picker asks too often.** On 20 prompts that have one correct dataset, it offered a dataset choice instead of selecting the dataset. An example is "Display grassland extent on the map". This is its largest cause of failures.
- **jev cannot ask.** jev returns one option, so it fails all 4 prompts where the correct answer is to ask the user (for example, "Show urban areas on the map"). This is the "many matches" open question below.
- **jev declines correctly in the agent.** It passed 14 of the 15 prompts that have no map layer. The one failure was the orchestrator, which searched the blogs.
- **Two errors that are only jev errors:**
  - "TCD layer" (tree canopy density) selected tree cover loss.
  - "Tampilkan peringatan deforestasi di peta" (Indonesian: "show deforestation alerts on the map") selected tree cover loss in 2 of 3 trials.
- **Six prompts did not get to the picker.** The orchestrator sent colloquial prompts (for example, "where'd the trees go, map it") to the blog search or to `pick_aoi`. A change of picker does not fix these.
- **The agent model uses the same number of tokens with the two pickers** (approximately 17,500 input tokens for each trial). The difference in cost is only the picker step.

The results for each prompt are in the appendix at the end of this document.

**Limits of this test**

- The test ran on a local stack, not in production. The times are local, but the difference between the pickers is valid.
- The integration code is on the branch `jev-dataset-picker` in project-zeno. The prompts and the results are on the branch `challenge-map` in gnw-gold-evals (`results/challenge/runs/20260925T113115Z_local.json` for the current picker, `20260925T121040Z_local.json` for jev). These branches are not yet pushed.

## Next steps for dataset selection

### 1. Go / no-go

We do not yet know how the current picker (RAG + LLM) scores on the same queries. Measure this first.

- Run the current `pick_dataset` on the same 178 queries. Also add 20–30 new decline cases (no matching dataset, or more than one possible dataset).
- Run jev on the same queries, with the short instruction and short descriptions.
- **Go** if all of these are true:
  - jev is as accurate as the current picker, or better.
  - jev declines valid queries less often than the current picker, or equally often.
  - jev handles "no match" and "many matches" acceptably, with the probability rules below.
  - A provider is available with acceptable limits, costs and data terms.

### 2. Implementation (if go)

The current picker returns more than a dataset. Each part needs a replacement:

| Output | Now | With jev |
|---|---|---|
| Candidates | RAG shortlist (5) | All datasets in the agent profile |
| Dataset | LLM | jev choice |
| Context layer, LGMS layer, parameters | LLM | Second jev call, with only the options of the selected dataset (after the AOI extent filter). Only for datasets that have these options. |
| Dates | LLM clamps to the dataset range | Code: clamp the orchestrator dates to the dataset range |
| Reason text | LLM, in the user language | Short template from the dataset card. The orchestrator writes the answer to the user. |
| Suggested datasets | LLM | From probabilities: if no option is clearly best, offer the top 2–3 options in the dataset-choice nudge |
| "No dataset" | LLM | `none` wins, or all probabilities are low |

Steps:

1. **Catalog:** add a short selection description to each dataset YAML. Keep the long LLM text for analysis only.
2. **Client:** add a small jev client with a timeout, retries and a setting for the provider and model.
3. **Selector:** add the jev path to `pick_dataset` behind a feature flag. Use the current LLM path as a fallback for errors, time-outs and low confidence.
4. **Shadow mode:** in production, run jev next to the current picker and log the differences. There is no change for users. Use the logs to set the confidence thresholds.
5. **Switch:** turn on jev for one agent profile, then for all.
6. **Clean up:** remove the RAG step, the embeddings index and its versioning, and the unused LLM selection text.

### Later

- Test `pick_aoi` candidate selection with jev. Use the existing pick_aoi tests and the GOLD AOI labels.
- Look at other decisions in the agent: nudges and off-topic checks.

## Risks

jev is new. The OpenRouter decisions endpoint (`/api/alpha/decisions`) is an alpha release.

- The API, the model versions, the pricing or the availability can change without notice.
- The open model on `api.codiv.ai` has a low rate limit.
- Only one company makes jev.

To decrease the risk:

- Keep jev behind a feature flag, with the current LLM path as the fallback.
- Use a fixed model version (for example `typesafe/jev-1.13`), not "latest".
- Run the test in PR #841 again before each model or endpoint change.
- Do not remove the LLM path until the endpoint is stable.

## Open questions

- **No match or many matches.** jev returns one option. How do we show "no dataset fits" and "these 2–3 datasets can help" (the current `suggested_datasets` case)? We can possibly use the probabilities (for example, all options above a threshold).
- **Low confidence.** At what probability do we ask the user or fall back to the LLM?
- **Two sets of descriptions.** Do we keep jev descriptions next to the LLM text in the catalog YAML, or make one text for both?
- **Which provider.** The open model has a low rate limit (429 errors at more than 2 parallel calls). The OpenRouter endpoint is alpha. What are the costs, limits and data terms for production?
- **Languages.** Is jev as good on non-English queries? We tested only a few.
- **Catalog size.** Without RAG, jev sees all datasets. This works for 11 datasets. At what number of datasets do we need a pre-filter again?

## Appendix: results for each prompt, current picker and jev

The results of the end-to-end test for each of the 200 prompts. Each prompt ran 3 times with each picker.

- **Expected:** the dataset IDs that are correct. "or" means that the agent can select any of them. "none" means that the agent must not select a dataset. "ask" means that the agent must offer a choice of datasets.
- **Picks:** the result of each trial, as a dataset ID. "×3" means the same result in all 3 trials. "/primary" and "/intact" are the context layers. "nudge" means the agent offered a choice of datasets. "area question" means the agent asked for a place. "none" means no dataset. "(called …)" names a tool that the agent called in one or more trials. Each trial that calls it fails, so the prompt fails if 2 or more trials call it.
- **Dataset IDs:** 1 land cover, 2 grasslands, 3 natural lands, 4 tree cover loss, 5 tree cover gain, 6 forest GHG net flux, 7 tree cover, 8 tree cover loss by driver, 9 sLUC emission factors, 10 tree cover loss from fires, 11 integrated alerts.
- **Why a prompt with the correct picks can fail:** the "no map layer" prompts also check the text of the answer. For example, 187 selects sLUC in all trials with the two pickers, but the explanation of the current picker was judged incorrect.

| Case | Cohort | Level | Prompt | Expected | RAG | RAG picks | jev | jev picks |
|---|---|---|---|---|---|---|---|---|
| 001 | land-cover | easy | Show land cover on the map | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 002 | land-cover | easy | Put the land cover map on | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 003 | land-cover | easy | Show me a map of land cover classes | 1 | pass | 1 · 1 · nudge | pass | 1 ×3 |
| 004 | land-cover | easy | Display land cover on the map | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 005 | land-cover | medium | Show where cropland and built-up land are on the map | 1 | pass | 1 · nudge · 1 | pass | 1 ×3 |
| 006 | land-cover | medium | Map the change in land cover classes over time | 1 | **fail** | nudge ×3 | pass | 1 ×3 |
| 007 | land-cover | medium | Show land cover change on the map | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 008 | land-cover | medium | Show me the bare ground, water and snow classes on the map | 1 | **fail** | nudge ×3 | pass | 1 ×3 |
| 009 | land-cover | medium | Map what the land is covered by: trees, crops, water, built-up | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 010 | land-cover | hard | landcover | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 011 | land-cover | hard | lulc map | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 012 | land-cover | hard | show landcovr change | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 013 | land-cover | hard | map of what covers the land | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 014 | grasslands | easy | Show natural grasslands on the map | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 015 | grasslands | easy | Display grassland extent on the map | 2 | **fail** | nudge ×3 | pass | 2 ×3 |
| 016 | grasslands | easy | Show me natural and semi-natural grasslands on the map | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 017 | grasslands | easy | Put natural grassland on the map | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 018 | grasslands | medium | Map savannas, shrublands and natural grasslands | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 019 | grasslands | medium | Show where natural grassland has been gained or lost | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 020 | grasslands | medium | Show the extent of semi-natural grasslands | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 021 | grasslands | medium | Show me non-cultivated grasslands on the map | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 022 | grasslands | medium | Map natural grassland change over time | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 023 | grasslands | hard | rangelands map | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 024 | grasslands | hard | show me the prairies and steppes | 2 | **fail** | 2 ×3 (called generate_insights, pull_data) | pass | 2 · 2 · none (called generate_insights, pull_data) |
| 025 | grasslands | hard | natrual grasslands | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 026 | grasslands | hard | wild grass areas on the map | 2 | pass | 2 · none · 2 | pass | 2 ×3 |
| 027 | natural-lands | easy | Show natural lands on the map | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 028 | natural-lands | easy | Show the natural lands map | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 029 | natural-lands | easy | Display natural and non-natural land on the map | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 030 | natural-lands | easy | Show me where land is natural or non-natural on the map | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 031 | natural-lands | medium | Map natural forests, natural short vegetation and natural water | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 032 | natural-lands | medium | Show the baseline of natural ecosystems for conversion-free commitments | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 033 | natural-lands | medium | Show the non-natural tree cover and crop areas on the map | 3 | **fail** | nudge ×3 | pass | 3 ×3 |
| 034 | natural-lands | medium | Map natural peat forest and wetland natural forest | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 035 | natural-lands | medium | Show a map separating natural forest from non-natural tree cover | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 036 | natural-lands | hard | SBTN map | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 037 | natural-lands | hard | nat lands layer | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 038 | natural-lands | hard | show the no-conversion baseline | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 039 | natural-lands | hard | natural vs not natural | 3 | **fail** | none ×3 (called search_blogs) | **fail** | none ×3 (called search_blogs) |
| 040 | tcl | easy | Show tree cover loss on the map | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 041 | tcl | easy | Display annual tree cover loss on the map | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 042 | tcl | easy | Show me where tree cover has been lost | 4 | pass | none · 4 · 4 | pass | 4/primary ×3 |
| 043 | tcl | easy | Put tree cover loss on the map | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 044 | tcl | medium | Map where trees have been lost year by year | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 045 | tcl | medium | Show tree cover loss at 50% canopy density | 4 ([{"name":"canopy_cover","values":[50]}]) | pass | 4 ×3 | pass | 4 · 4/primary · 4 |
| 046 | tcl | medium | Show tree cover loss using a 75% canopy threshold on the map | 4 ([{"name":"canopy_cover","values":[75]}]) | pass | 4 ×3 | pass | 4 ×3 |
| 047 | tcl | medium | Show me the annual forest canopy loss layer | 4 | pass | 4/primary ×3 | pass | 4/primary ×3 |
| 048 | tcl | medium | Map loss of trees taller than 5 metres | 4 | pass | 4 ×3 | pass | 4 ×3 |
| 049 | tcl | hard | Hansen loss layer | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 050 | tcl | hard | tree cover los | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 051 | tcl | hard | where'd the trees go, map it | 4 | **fail** | none ×3 | **fail** | none ×3 |
| 052 | tcl | hard | TCL | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 053 | tc-gain | easy | Show tree cover gain on the map | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 054 | tc-gain | easy | Display tree cover gain | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 055 | tc-gain | easy | Show me where tree cover has been gained | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 056 | tc-gain | easy | Put tree cover gain on the map | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 057 | tc-gain | medium | Map where trees have grown back | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 058 | tc-gain | medium | Show areas where new tree cover has grown | 5 | pass | 5 ×3 (called generate_insights, pull_data) | pass | 5 ×3 (called generate_insights, pull_data) |
| 059 | tc-gain | medium | Show me forest regrowth on the map | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 060 | tc-gain | medium | Map where tree canopy has increased | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 061 | tc-gain | medium | Show tree cover gain from plantations and natural regrowth | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 062 | tc-gain | hard | treecover gain | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 063 | tc-gain | hard | regrowth map | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 064 | tc-gain | hard | where are trees coming back | 5 | **fail** | none · 5 · 5 (called generate_insights, pull_data, search_blogs) | **fail** | none · 5 · 5 (called generate_insights, pull_data, search_blogs) |
| 065 | tc-gain | hard | reforestation layer | 5 | **fail** | nudge ×3 | pass | 5 ×3 |
| 066 | ghg-flux | easy | Show forest greenhouse gas net flux on the map | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 067 | ghg-flux | easy | Display forest carbon net flux on the map | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 068 | ghg-flux | easy | Show me the net GHG flux from forests | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 069 | ghg-flux | easy | Put forest greenhouse gas flux on the map | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 070 | ghg-flux | medium | Map where forests are a net carbon sink or source | 6 | pass | 6 ×3 | pass | none · 6 · 6 |
| 071 | ghg-flux | medium | Show the balance of forest carbon emissions and removals on the map | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 072 | ghg-flux | medium | Show where forests absorb more carbon than they emit | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 073 | ghg-flux | medium | Map net forest greenhouse gas emissions and removals | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 074 | ghg-flux | medium | Show me the carbon emissions from deforestation on the map | 4 or 6 | **fail** | nudge ×3 | pass | 4/primary ×3 |
| 075 | ghg-flux | hard | carbon sink map | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 076 | ghg-flux | hard | forest flux layer | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 077 | ghg-flux | hard | net ghg forests | 6 | **fail** | none · none · 6 | pass | 6 ×3 |
| 078 | ghg-flux | hard | sinks vs sources | 6 | **fail** | none ×3 (called search_blogs) | **fail** | none ×3 (called search_blogs) |
| 079 | tree-cover | easy | Show tree cover on the map | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 080 | tree-cover | easy | Display tree cover density on the map | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 081 | tree-cover | easy | Show me tree canopy cover on the map | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 082 | tree-cover | easy | Put tree cover on the map | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 083 | tree-cover | medium | Map tree canopy density | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 084 | tree-cover | medium | Show tree cover with at least 50% canopy density | 7 ([{"name":"canopy_cover","values":[50]}]) | pass | 7 ×3 | pass | 7 ×3 |
| 085 | tree-cover | medium | Show tree cover at a 25% canopy threshold | 7 ([{"name":"canopy_cover","values":[25]}]) | pass | 7 ×3 | pass | 7 ×3 |
| 086 | tree-cover | medium | Show where trees taller than 5 metres are on the map | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 087 | tree-cover | medium | Show the tree cover baseline map | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 088 | tree-cover | hard | TCD layer | 7 | pass | 7 ×3 | **fail** | 4/primary ×3 |
| 089 | tree-cover | hard | tree canopy | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 090 | tree-cover | hard | treecover | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 091 | tree-cover | hard | how dense are the trees, map it | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 092 | tcl-drivers | easy | Show the drivers of tree cover loss on the map | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 093 | tcl-drivers | easy | Display tree cover loss by dominant driver | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 094 | tcl-drivers | easy | Show me what caused tree cover loss on the map | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 095 | tcl-drivers | easy | Put the drivers of tree cover loss on the map | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 096 | tcl-drivers | medium | Map why trees were lost | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 097 | tcl-drivers | medium | Show where tree cover loss came from agriculture, logging or wildfire | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 098 | tcl-drivers | medium | Show tree cover loss caused by permanent agriculture and hard commodities | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 099 | tcl-drivers | medium | Map the dominant causes of forest loss | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 100 | tcl-drivers | medium | Show me which tree loss was from shifting cultivation | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 101 | tcl-drivers | hard | deforestation drivers map | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 102 | tcl-drivers | hard | what's killing the trees, show me | 8 | **fail** | none ×3 | **fail** | none ×3 |
| 103 | tcl-drivers | hard | driver layer | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 104 | tcl-drivers | hard | commodity driven deforestation | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 105 | tcl-fires | easy | Show tree cover loss due to fires on the map | 10 | pass | 10 ×3 | pass | 10 ×3 |
| 106 | tcl-fires | easy | Display tree cover loss from fires | 10 | pass | 10 ×3 | pass | 10 ×3 |
| 107 | tcl-fires | easy | Show me where fires caused tree cover loss | 10 | pass | 10 · 10 · nudge | pass | 10/primary · 10 · 10 |
| 108 | tcl-fires | easy | Put fire-related tree cover loss on the map | 10 | pass | 10 ×3 | pass | 10 ×3 |
| 109 | tcl-fires | medium | Map tree cover loss from fires versus other causes | 10 | pass | 10 ×3 | pass | 10 ×3 |
| 110 | tcl-fires | medium | Show forest loss caused by wildfires | 10 | **fail** | nudge ×3 | pass | 10/primary ×3 |
| 111 | tcl-fires | medium | Show where trees were lost to burning | 10 | pass | 10 ×3 | pass | 10/primary · 10 · 10/primary |
| 112 | tcl-fires | medium | Show fire-driven tree cover loss at 50% canopy density | 10 ([{"name":"canopy_cover","values":[50]}]) | pass | 10 ×3 | pass | 10 · 8 · 10 |
| 113 | tcl-fires | medium | Map annual tree loss from fires | 10 | pass | 10 ×3 | pass | 10/primary · 10/primary · 10 |
| 114 | tcl-fires | hard | burn scars in forests | 10 | **fail** | none ×3 (called search_blogs) | **fail** | none ×3 (called search_blogs) |
| 115 | tcl-fires | hard | fire loss layer | 10 | pass | 10 ×3 | pass | 10/primary ×3 |
| 116 | tcl-fires | hard | trees lost to fire | 10 | pass | none · 10 · 10 | pass | 10/primary ×3 |
| 117 | tcl-fires | hard | wildfire tree los | 10 | pass | 10 ×3 | pass | 10/primary · 10 · 10 |
| 118 | integrated-alerts | easy | Show integrated alerts on the map | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 119 | integrated-alerts | easy | Display deforestation alerts on the map | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 120 | integrated-alerts | easy | Show me forest disturbance alerts | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 121 | integrated-alerts | easy | Put disturbance alerts on the map | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 122 | integrated-alerts | medium | Map near-real-time vegetation disturbance alerts | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 123 | integrated-alerts | medium | Show high-confidence clearing alerts | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 124 | integrated-alerts | medium | Show me the latest deforestation alerts | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 125 | integrated-alerts | medium | Map alerts that combine GLAD and RADD | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 126 | integrated-alerts | medium | Show recent tree clearing alerts | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 127 | integrated-alerts | hard | GLAD alerts | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 128 | integrated-alerts | hard | RADD | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 129 | integrated-alerts | hard | defor alerts | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 130 | integrated-alerts | hard | show clearing alerts asap | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 131 | multilingual | easy | Muéstrame las alertas de deforestación en el mapa | 11 | pass | 11 ×3 | pass | 11 ×3 |
| 132 | multilingual | easy | Muestra la ganancia de cobertura arbórea en el mapa | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 133 | multilingual | medium | Muéstrame en el mapa las causas de la pérdida de cobertura arbórea | 8 | pass | 8 · 8 · nudge | pass | 8 ×3 |
| 134 | multilingual | medium | Muestra la pérdida de bosque primario en el mapa | 4 / primary_forest | pass | 4/primary ×3 | pass | 4/primary ×3 |
| 135 | multilingual | hard | pon en el mapa los arboles perdidos por incendios | 10 | pass | 10 ×3 | pass | 10/primary ×3 |
| 136 | multilingual | easy | Mostre a cobertura do solo no mapa | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 137 | multilingual | easy | Mostre a cobertura arbórea no mapa | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 138 | multilingual | medium | Mostre no mapa as terras naturais e não naturais | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 139 | multilingual | medium | Mostre a perda de floresta primária no mapa | 4 / primary_forest | pass | 4/primary ×3 | pass | 4/primary ×3 |
| 140 | multilingual | hard | mapa do fluxo liquido de gases de efeito estufa das florestas | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 141 | multilingual | easy | Affiche la perte de couvert arboré sur la carte | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 142 | multilingual | easy | Montre-moi l'occupation du sol sur la carte | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 143 | multilingual | medium | Affiche le flux net de gaz à effet de serre des forêts sur la carte | 6 | pass | 6 ×3 | pass | 6 ×3 |
| 144 | multilingual | medium | Montre la densité du couvert arboré sur la carte | 7 | pass | 7 ×3 | pass | 7 ×3 |
| 145 | multilingual | hard | prairies naturelles sur la carte stp | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 146 | multilingual | easy | Tampilkan kehilangan tutupan pohon di peta | 4 | pass | 4 ×3 | pass | 4/primary ×3 |
| 147 | multilingual | easy | Tampilkan peringatan deforestasi di peta | 11 | pass | 11 ×3 | **fail** | 4/primary · 11 · 4/primary |
| 148 | multilingual | medium | Tampilkan penyebab hilangnya tutupan pohon di peta | 8 | pass | 8 ×3 | pass | 8 ×3 |
| 149 | multilingual | medium | Tampilkan kehilangan tutupan pohon akibat kebakaran di peta | 10 | pass | 10 ×3 | pass | 10/primary · 10 · 10 |
| 150 | multilingual | hard | peta lahan alami vs non alami | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 151 | multilingual | easy | Nionyeshe tahadhari za ukataji miti kwenye ramani | 11 | pass | 11 ×3 | pass | 11 · 11 · 4/primary |
| 152 | multilingual | easy | Onyesha kifuniko cha ardhi kwenye ramani | 1 | pass | 1 ×3 | pass | 1 ×3 |
| 153 | multilingual | medium | Nionyeshe nyasi asilia kwenye ramani | 2 | pass | 2 ×3 | pass | 2 ×3 |
| 154 | multilingual | medium | Onyesha ongezeko la miti kwenye ramani | 5 | pass | 5 ×3 | pass | 5 ×3 |
| 155 | multilingual | hard | sababu za kupotea kwa miti, ramani | 8 | pass | 8 ×3 | **fail** | 8 · none · area question |
| 156 | context-layer | easy | Show primary forest loss on the map | 4 / primary_forest | pass | 4/primary ×3 | pass | 4/primary ×3 |
| 157 | context-layer | medium | Map tree cover loss inside primary forests | 4 / primary_forest | pass | 4/primary ×3 | pass | 4/primary ×3 |
| 158 | context-layer | hard | old-growth rainforest loss on the map | 4 / primary_forest | pass | 4/primary ×3 | pass | 4/primary ×3 |
| 159 | context-layer | easy | Show tree cover loss in intact forest landscapes on the map | 4 / intact_forest | pass | 4/intact ×3 | pass | 4/intact ×3 |
| 160 | context-layer | medium | Map where intact forests are being lost | 4 / intact_forest | pass | 4/intact · 4/intact · 4 | pass | 4/intact ×3 |
| 161 | context-layer | hard | IFL loss layer pls | 4 / intact_forest | pass | 4/intact ×3 | pass | 4/intact ×3 |
| 162 | context-layer | medium | Show fire-driven tree cover loss in primary forests on the map | 10 / primary_forest | pass | 10/primary ×3 | pass | 10/primary ×3 |
| 163 | context-layer | hard | burnt primary forest map | 10 / primary_forest | pass | 10/primary ×3 | pass | 10/primary ×3 |
| 164 | context-layer | medium | Show tree cover loss from fires within intact forest landscapes | 10 / intact_forest | pass | 10/intact ×3 | pass | 10/intact ×3 |
| 165 | context-layer | hard | map fire loss in IFLs | 10 / intact_forest | **fail** | none · 10/intact · none (called generate_insights, pull_data) | **fail** | 10/intact · area question · none (called generate_insights, pull_data) |
| 166 | context-layer | medium | Show tree cover within primary forests on the map | 7 / primary_forest | pass | 7/primary ×3 | pass | 7/primary ×3 |
| 167 | context-layer | hard | Where is the primary forest? Put it on the map | 7 or 4 / primary_forest | pass | 7/primary ×3 | pass | 4/primary ×3 |
| 168 | context-layer | medium | Show all tree cover loss on the map, including plantations and secondary forest | 4 / no layer | pass | 4 ×3 | pass | 4 ×3 |
| 169 | context-layer | medium | Map tree cover loss from fires across all tree cover, not just primary forest | 10 / no layer | pass | 10 ×3 | pass | 10 ×3 |
| 170 | context-layer | medium | Show tree cover density for all trees, plantations included | 7 / no layer | pass | 7 ×3 | pass | 7 ×3 |
| 171 | ambiguous | hard | Show me deforestation | 4 or 11 | pass | 4/primary · nudge · 4/primary | pass | 4/primary ×3 |
| 172 | ambiguous | medium | Show me forests on the map | 7 or 3 or 1 | **fail** | nudge · nudge · 7/primary | pass | 1 ×3 |
| 173 | ambiguous | hard | Show carbon on the map | 6 or 4 | **fail** | nudge ×3 | pass | 6 ×3 |
| 174 | ambiguous | medium | Show fires on the map | 10 or none | pass | nudge · 10 · 10 | pass | 10/primary ×3 |
| 175 | ambiguous | medium | Show urban areas on the map | ask (nudge: Global land cover, SBTN) | pass | nudge ×3 | **fail** | 1 ×3 |
| 176 | ambiguous | medium | Show wetlands on the map | 1 or 3 | **fail** | nudge ×3 | pass | 1 ×3 |
| 177 | ambiguous | medium | Show land use on the map | 1 or 3 | pass | 1 ×3 | pass | 1 ×3 |
| 178 | ambiguous | medium | Show plantations on the map | 3 | **fail** | nudge · 3 · nudge | **fail** | 3 · 1 · 1 |
| 179 | ambiguous | medium | Show savannas on the map | 2 or 1 | pass | 2 ×3 | pass | 2 ×3 |
| 180 | ambiguous | hard | Show clearing on the map | 11 or 4 | pass | 4 · 4 · 11 | pass | 11 · 4/primary · 4/primary |
| 181 | ambiguous | medium | Show forest change on the map | ask (nudge: Tree cover loss, Tree cover gain, Global land cover) | **fail** | nudge ×3 | **fail** | 4/primary ×3 |
| 182 | ambiguous | medium | Show mangroves on the map | 3 | pass | 3 ×3 | pass | 3 ×3 |
| 183 | ambiguous | medium | Show cropland on the map | 1 or 3 | **fail** | nudge ×3 | pass | 1 ×3 |
| 184 | ambiguous | hard | Show emissions on the map | ask (nudge: Forest greenhouse gas net flux, Tree cover loss) | **fail** | nudge ×3 | **fail** | 4 ×3 |
| 185 | ambiguous | hard | Show grass on the map | ask (nudge: Global natural/semi-natural grassland extent, Global land cover) | pass | nudge ×3 | **fail** | 2 ×3 |
| 186 | unmappable | easy | Show crop deforestation emission factors on the map | 9 or none | pass | 9 ×3 | pass | 9 ×3 |
| 187 | unmappable | medium | Map the sLUC emission factors for soy | 9 or none | **fail** | 9 ×3 | pass | 9 ×3 |
| 188 | unmappable | medium | Put the deforestation emissions per tonne of beef on the map | 9 or none | **fail** | nudge · none · none | pass | 9 ×3 |
| 189 | unmappable | hard | sLUC EFs map | 9 or none | pass | nudge ×3 | pass | 9 ×3 |
| 190 | unmappable | easy | Show rainfall on the map | none | pass | none ×3 | pass | none ×3 |
| 191 | unmappable | easy | Show me a temperature map | none | pass | none ×3 | pass | none ×3 |
| 192 | unmappable | medium | Map drought conditions | none | pass | none ×3 | pass | none ×3 (called search_blogs) |
| 193 | unmappable | medium | Show flood risk on the map | none | pass | none ×3 | pass | none ×3 (called search_blogs) |
| 194 | unmappable | medium | Show sea level rise on the map | none | pass | none ×3 | pass | none ×3 |
| 195 | unmappable | medium | Show air pollution on the map | none | pass | none ×3 | pass | none ×3 |
| 196 | unmappable | medium | Show wind speeds on the map | none | pass | none ×3 | pass | none ×3 |
| 197 | unmappable | hard | Put precipitation anomalies on the map | none | pass | none ×3 | pass | none ×3 |
| 198 | unmappable | medium | Show jaguar range on the map | none | pass | none ×3 (called search_blogs) | **fail** | none ×3 (called search_blogs) |
| 199 | unmappable | medium | Show population density on the map | none | pass | none ×3 | pass | none ×3 |
| 200 | unmappable | hard | soil moisture map | none | pass | none ×3 | pass | none ×3 |
