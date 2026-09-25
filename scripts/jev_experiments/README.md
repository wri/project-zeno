# jev dataset-picker experiments

These experiments measure how the instruction text and the dataset descriptions change the accuracy of jev on the dataset-selection step. Each call asks one choice question: which dataset answers the user query, or `none`. The findings are in PR #841.

## Case sets

| Set | Cases | Source | Use |
|---|---|---|---|
| `dev` | 89 | `CASES` and `GOLD_CASES` in `scripts/jev_dataset_test.py` | Tune and compare variants |
| `holdout` | 51 | GOLD sheet rows that are not in `GOLD_CASES` | Validate the finalists one time |
| `holdout2` | 38 | `tests/evals/datasets/*.csv` and `data/gold.csv`, without repeats of the other sets | Validate the finalists one time |

The holdout cases are in `holdout_cases.py`, so the source sheets are not necessary. Only the `dev` set has cases that expect `none` (6 cases).

## Variants

A variant name is `<description>:<instruction>[:<none mode>]`.

- Descriptions (`variants.py`):
  - `base`: the fields that the picker LLM gets (description, selection hints, content date, context layers, parameters).
  - `no_lgms`: `base` without the sentences about LGMS. LGMS is not a choice in the default profile.
  - `no_xref`: `base` without the clauses that send the reader to a different dataset.
  - `cards`: one fixed template for each dataset: what it measures, units, time range, time step, breakdowns and its own limits. The text comes only from the catalog YAML and does not name other datasets.
- Instructions: `rules` (the picker `SELECTION_RULES`), `short`, `neutral`.
- None modes: `std` (default), `topic` (a different text for `none`), `drop` (no `none` choice).

Do not change a variant to fix one test case. Change the full catalog in the same way, and then validate on the holdout sets.

## Run

```
uv run python scripts/jev_experiments/run.py dev 3 base:rules cards:neutral
ONLY=openrouter uv run python scripts/jev_experiments/run.py holdout 1 cards:neutral
uv run python scripts/jev_experiments/analyze.py            # all variants
uv run python scripts/jev_experiments/analyze.py cards:neutral base:rules
```

- `run.py` adds one line for each case and run to `results/<backend>.jsonl`. Each line has the choice, the probabilities for each choice (rounded to 3 decimals, values below 0.001 removed), the confidence, the time and the cost.
- `api.codiv.ai` returns `429 Too Many Requests` at more than approximately 2 parallel calls. `run.py` uses 2 workers for that backend.
- `results/summary.txt` is the `analyze.py` output for the saved results.
