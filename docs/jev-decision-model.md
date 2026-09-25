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

## Suggested next steps

1. Test `pick_aoi` candidate selection with jev. Use the existing pick_aoi tests and the GOLD AOI labels.
2. Test the dataset, context layer and parameter questions together, with the short instructions.
3. Collect more decline cases: queries with no matching dataset, and queries where more than one dataset can answer.
4. Run jev behind a flag in the real `pick_dataset` step, with the LLM as fallback. Compare on the full GOLD eval.

## Open questions

- **No match or many matches.** jev returns one option. How do we show "no dataset fits" and "these 2–3 datasets can help" (the current `suggested_datasets` case)? We can possibly use the probabilities (for example, all options above a threshold).
- **Low confidence.** At what probability do we ask the user or fall back to the LLM?
- **Two sets of descriptions.** Do we keep jev descriptions next to the LLM text in the catalog YAML, or make one text for both?
- **Which provider.** The open model has a low rate limit (429 errors at more than 2 parallel calls). The OpenRouter endpoint is alpha. What are the costs, limits and data terms for production?
- **Languages.** Is jev as good on non-English queries? We tested only a few.
- **Catalog size.** Without RAG, jev sees all datasets. This works for 11 datasets. At what number of datasets do we need a pre-filter again?
