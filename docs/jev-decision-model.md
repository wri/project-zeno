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

## Open questions

- **No match or many matches.** jev returns one option. How do we show "no dataset fits" and "these 2–3 datasets can help" (the current `suggested_datasets` case)? We can possibly use the probabilities (for example, all options above a threshold).
- **Low confidence.** At what probability do we ask the user or fall back to the LLM?
- **Two sets of descriptions.** Do we keep jev descriptions next to the LLM text in the catalog YAML, or make one text for both?
- **Which provider.** The open model has a low rate limit (429 errors at more than 2 parallel calls). The OpenRouter endpoint is alpha. What are the costs, limits and data terms for production?
- **Languages.** Is jev as good on non-English queries? We tested only a few.
- **Catalog size.** Without RAG, jev sees all datasets. This works for 11 datasets. At what number of datasets do we need a pre-filter again?
