# Zap evals

The map set measures the plan that zap mode (`POST /api/zap`) makes for the
map. The dashboard set is at the end of this file ("The dashboard set").
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
| `follow-up` | Pairs. The second prompt runs on the state after the first prompt (`follows`). The dataset, the dates and the forest type must stay, unless the prompt changes them. The script sends the `state` of the plan of the first prompt as `current` (see "Run the eval"). |
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

A follow-up case sends the `state` of the plan of its first prompt as
`current`, as the frontend does. Thus, a wrong first plan can also make the
follow-up fail. `--no-chain` sends the fixed `current` of the case instead.
When a case runs without its first prompt (`--ids`), it sends the fixed
`current`.

The script prints the correct counts for each field, the counts for each
kind, the median latency, the path that gave each value (`Value sources`: jev,
clairic or code) and the failed fields. It writes the raw results
to `tests/evals/zap/results/<date>-<part>.json`. `--ids` runs only some
cases. `--label` adds a word to the file name, for example the planner
version.

## The dashboard set

The dashboard set measures the plan that zap makes on a dashboard page
(phases 4 and 5 of `docs/zap-mode-plan.md`). The cases run against three
fixed dashboards in `dashboards.yaml`. The script gives the planner a
`ZapDashboard` for each dashboard, so the run needs no dashboard rows and no
database. Each section and widget of a fixed dashboard has an id. A chart
or a dataset map also has its `analysis` (the dataset, the dates, the
forest type), which `change_period` builds again.

| File | Use |
|---|---|
| `dashboards.yaml` | The fixed dashboards: the id, the name, the area, the section titles and the widget texts. |
| `dashboard-dev.yaml` | The dev part. Use it to tune the planner and the thresholds. |
| `dashboard-test.yaml` | The test part. Do not tune on it. |

The kinds of cases:

| Kind | What it tests |
|---|---|
| `chart`, `map`, `template`, `imagery` | A request that adds one item. |
| `add-section`, `move`, `resize`, `rename`, `change-period`, `remove` | A request for one edit of phase 5. Some cases name a target, a place or a name that is not on the dashboard: the plan must have no steps. |
| `near-titles` | An edit of one of two widgets with near titles ("Tree cover loss per year", "Primary forest loss per year"). |
| `last-edit` | "remove that" or "make it half width" after an addition. `add_widgets` and `add_sections` put the new items on the dashboard, and `last` gives their ids. |
| `outside` | A request that stays outside zap (tier 3): delete or publish the dashboard, write a note. The plan must have no steps. |
| `no-change` | A request that changes nothing: a greeting, a question, more than one area. |
| `unclear` | A request that does not say what to add. If the plan adds something, it must need a confirmation. |
| `follow-up` | A request that refers to the last addition. `current` gives the state of the last addition. |

The format of a case:

```yaml
- id: dd-01
  dashboard: para          # a key of dashboards.yaml
  kind: chart
  prompt: add a chart of tree cover loss since 2015
  current: {dataset: 4, start: "2015-01-01", end: "2025-12-31"}  # optional
  expect:
    action: add_chart      # add_chart, add_map, add_template, add_imagery,
                           # none (no steps), or a list
    dataset: 4             # an id or a list
    start: "2015-01-01"    # with end, or `ranges`; null is the full dates
    end: "2026-11-12"
    relative: false
    context: null          # default null
    canopy: null           # default null (30)
    template: nrt-monitoring
    cloud: 20              # the maximum cloud cover of imagery, default 20
    target: w-para-loss-map  # a widget id, a section id or "dashboard"
    destination: top       # move: a section id or "top"
    size: single           # resize: single (half width) or double
    title: Fire season     # rename, add_section: the new name
    widgets: false         # remove of a section: true removes its widgets
    confirm: false         # true, false or any (the default)
    tier: 1                # default: 2 for confirm true, 1 for false
```

A case can also have:

```yaml
  add_sections: [{id: sec-new, title: Peat}]   # items of the last edit
  add_widgets: [{id: w-new, kind: chart, title: Loss, section: sec-new}]
  last: [sec-new, w-new]   # current.last_section_ids and last_widget_ids
  choose: {target: "widget:w-new"}   # ZapRequest.choose
```

Scoring:

| Field | Correct when |
|---|---|
| `action` | The kind of the first step is one of the expected actions. A plan with no steps is `none`. |
| `dataset`, `context`, `canopy` | As in the map set, on the analysis body (`add_chart`) or the map layer (`add_map`). |
| `time` | `add_chart` and `add_map`: as in the map set. `add_imagery`: the target date and the window agree with the ones that the planner makes from the expected range. |
| `template`, `cloud` | The value is one of the expected values. |
| `target`, `destination`, `size`, `title`, `widgets` | The value of the edit step is one of the expected values. `time` of `change_period` is scored as for `add_chart`. |
| `tier` | The `tier` of the plan is the expected tier. Scored only for a plan with steps. |
| `confirm` | `needs_confirmation` agrees with `confirm`. Scored only for a plan with steps and a case with `confirm: true` or `false`. |

The fields of an addition or an edit are scored only when the expected
action is of that kind and the plan does it. A plan with steps and a wrong
field (also a wrong action) is a wrong plan. The report gives, for the
additions, the edits and the removals (a plan with a `remove` step): the
plans with steps, the wrong plans, the wrong plans that need no
confirmation (these are applied immediately), and the correct plans that
need a confirmation that the case does not need. It also gives the
requests that must change nothing and got no steps.

```bash
uv run python scripts/zap_eval.py dashboard-dev --env-file .env
uv run python scripts/zap_eval.py dashboard-test --env-file .env
```
