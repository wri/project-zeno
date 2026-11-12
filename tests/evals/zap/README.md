# Zap map eval

This set measures the plan that zap mode (`POST /api/zap`) makes for the map.
The script `scripts/zap_eval.py` calls `plan_zap` for each case with live
jev and the AOI database, and scores each field of the result separately.
The plan is in `docs/zap-mode-plan.md` ("Eval" and "Phases").

## The parts

| File | Use |
|---|---|
| `dev.yaml` | The dev part. Use it to write and tune the planner instructions. |
| `test.yaml` | The test part. Do not tune on it. Run it one time for each planner version that you compare. |

Both parts have the same kinds of cases:

| Kind | What it tests |
|---|---|
| `gold` | Single-area prompts from the GOLD set (`gnw-gold-evals`, `cases/v2`). The `source` key gives the GOLD id. |
| `multilingual` | GOLD prompts in other languages. |
| `free-range` | A date range that is not an option of jev, for example "from 2015 to 2020". |
| `month` | Months and days for the integrated alerts, for example "March 2026" or "15 June 2025". |
| `relative` | A period back from today, for example "the last 3 months". |
| `long-place` | A place name of more than four words. |
| `canopy` | A canopy cover value, also values that the dataset does not have, for example "12%". |
| `follow-up` | Pairs. The second prompt runs on the state after the first prompt (`follows`). The dataset, the dates and the forest type must stay, unless the prompt changes them. |
| `no-change` | Prompts that must change nothing on the map. |

## The format of a case

```yaml
- id: d-40
  kind: follow-up
  follows: d-39            # optional: the case that makes the current state
  source: gold 1-033       # optional
  tests: [time, context]   # the fields that the case is made to test
  prompt: since 2015
  current:                 # optional: the map state before the prompt
    dataset: 4
    area: {id: "gadm:BRA.14_1", name: "Pará, Brazil"}
    start: "2002-01-01"
    end: "2025-12-31"
    context: primary_forest
    canopy: null
  expect:                  # the map state after the plan
    dataset: 4             # a dataset id, a list of correct ids, or null
    area: gadm:BRA.14_1    # "source:src_id", a list, or null (no area)
    start: "2015-01-01"    # null: the full dates of the dataset
    end: "2026-11-12"
    relative: false        # true for a period back from today
    context: primary_forest  # a context layer, a list, or null
    canopy: null           # a percent, a list, or null (the default, 30)
  skip: [time]             # optional: fields that are not scored
  no_change: true          # optional: the plan must have no steps
```

Rules for `expect`:

- A key that is not in `expect` keeps its value from `current`. For a case
  with no `current`, the dataset and the area are null, the time is the full
  dates of the dataset, and the context layer and the canopy cover are null.
- `ranges: [[start, end], ...]` instead of `start` and `end` gives more than
  one correct range.
- All dates assume the `today` date at the top of the file.

## Scoring

The script applies the plan to `current` as the frontend does. A dataset step
sets the dataset, the dates, the context layer and the canopy cover. An area
step sets the area. With no step, the map keeps what it shows. Then the
script scores the state with these rules (from stac-zap `eval/score.ts`):

| Field | Correct when |
|---|---|
| `dataset` | The dataset id is one of the expected ids. |
| `area` | The `source:src_id` of the area is one of the expected areas. |
| `time` | The script clamps the expected range to the dates of the dataset on the map, as the planner does. A fixed range must then match to the day. A range back from today must end within 1 day and start within a fifth of its length. |
| `context` | The context layer is one of the expected layers. Scored only when the expected dataset has context layers. |
| `canopy` | The canopy cover is one of the expected values. No value and 30 are the same. Scored only when the expected dataset has a canopy cover parameter. |
| `no_change` | The plan has no steps. Scored only for cases with `no_change: true`. |

The time is not scored when the expected dataset is null. A case with an
error (for example a failed jev call) fails on each field that it scores.

The script fixes the date of `revise_date_range` to `today`, so an open
dataset (integrated alerts) ends on the same day in each run.

## Run the eval

The script needs `OPENROUTER_API_KEY` and `DATABASE_URL`. Do not source
`.env` in the shell, because that breaks docker. Give the file to the script:

```bash
uv run python scripts/zap_eval.py dev --env-file .env
uv run python scripts/zap_eval.py test --env-file .env
```

The script prints the correct counts for each field, the counts for each
kind, the median latency and the failed fields. It writes the raw results
to `tests/evals/zap/results/<date>-<part>.json`. `--ids` runs only some
cases. `--label` adds a word to the file name, for example the planner
version.
