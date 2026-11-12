# Zap mode plan: extraction, history, undo and dashboards

Status: proposal. Phase 1 (the map eval and its baseline) and phase 2
(Clairic extraction and the full current state) are done. The other phases
have no code.

## Goal

Zap mode changes the map from one request, with no agent and no text
generation. This plan extends it in four directions:

1. Read the place, the time and the numbers of a request with the Clairic
   extraction model. Keep jev for the decisions.
2. Keep a history of the requests in the browser. The history is a list of
   states, not a conversation.
3. Add an undo button on the map.
4. Let zap edit dashboards, with a confirmation for edits that are not
   clear or not safe.

Not in this plan: undo for dashboard edits. To take back a dashboard edit,
the user makes a new request, for example "remove that chart". A real undo
can come later.

## Review of zap mode today

Backend (`src/api/services/zap/`, PR #850): `POST /api/zap` is for admins
only. It gets the prompt and the current dataset and area. It makes two jev
calls and returns a plan of up to three steps: show a dataset, go to an
area, chart the dataset for the area. It changes nothing on the server.

Frontend (`wri/project-zeno-next`, branch `feat/zap-mode`, flag `ff=zap`):
`runZap` runs the steps in order. `ZapPanel` shows the steps and the jev
decisions. The store holds one plan. A new request replaces it.

Limits that this plan removes:

| Limit | Cause | Example that fails |
|---|---|---|
| A place of more than four words loses words | The place is an option list of 1 to 4 word spans (`place_spans`) | "Ciudad Autónoma de Buenos Aires" |
| No free date range | The period is an option list: a year, "since a year", three relative periods | "from 2015 to 2020", "alerts in March 2026", "the last 3 months" |
| A weak period answer is dropped | `PERIOD_THRESHOLD = 0.35` | "recent" splits between two options |
| A follow-up request loses the forest type and the canopy cover | `ZapCurrent` has only `dataset_id` and `area`. The planner builds the dataset again with no context layer | "primary forest loss in Pará", then "since 2015" |
| No history, no undo | The endpoint has no state, and the store holds one plan | |
| Map only | `useZapMode` is off on `/dashboards/*`, and no step kind writes a dashboard | |
| The chart step cannot select a chart | The step runs `/api/analyze`, which builds the default charts of the dataset | |
| No eval | The tests mock jev. No labelled set measures the plan quality | |

Limits that stay: one area for each request, English place names (this is a
limit of `search_aois`, not of the model), datasets 9 and 12 not offered.

## Design

### 1. Clairic for values, jev for decisions

The stac-zap tests of 2026-11-12 (`stac-zap/docs/decision-models.md`, Test
3) give the method. Clairic was correct on 84 of 85 values and on 16 of 16
requests that option lists cannot hold. jev was correct on 80 of 85 and 0
of 16. The cost increased from $0.00042 to $0.00050 for each request.

Clairic is on the OpenRouter extractions API (`/api/alpha/extractions`,
model `cloudflare/clairic`). It uses the `OPENROUTER_API_KEY` that zap has
now. No new credential is necessary.

New module `src/api/services/zap/extract.py`, a port of
`stac-zap/src/zap/extract.ts`:

| Call | State | Fields | Replaces |
|---|---|---|---|
| A | The request only | `place` (text), `canopy` (number, percent), `cloud` (number, percent), `title` (text) | The `place` question, the `canopy` question |
| B | The app context, today's date and the request | `when` (text), `start` (date), `end` (date) | The `period` question |

Rules from the stac-zap tests that the port keeps:

- The time fields go in their own call. In one call, a number such as "12%
  clouds" moved into the dates.
- Only the time call gets the app context. The place and the numbers were
  better with the request only.
- `when` tells if the request names a time. With today's date in the
  state, the model gives a range for each request.
- Code does the calendar. A season, a quarter, "the last 3 months" and
  "recent" get their range from code, from the words in `when`.

Rules that are new for Zeno:

- `revise_date_range` clamps the range to the dataset, as it does now.
- `canopy` snaps to the nearest value that the dataset permits. A value
  that is more than 5 points from a permitted value adds a note.
- `cloud` is only for imagery (see "Dashboard actions").
- `title` holds the words of the user for a name or a note, for example
  "rename the section to Fire season". Zap does not write text itself.

jev keeps these questions: `dataset`, `scope`, the `area` from the
`search_aois` results, `context`, and the new `action`, `target` and
`view` questions (see below).

Sequence for one request: calls A and B and the first jev call start at the
same time. Then `search_aois` runs on the place. Then the second jev call
selects the area and the dataset options. The total time stays near 1 s.

Fallback: when Clairic does not answer, the planner asks the `place`,
`period` and `canopy` questions of today. The extractions API is an alpha
release and Clairic is a preview model, so the old questions stay in the
code.

### 2. The full current state

`ZapCurrent` gets the dates, the context layer, the canopy cover, the page
(`map` or `dashboard`) and the dashboard id. The planner starts from this
state and changes only what the request names. This repairs the follow-up
defect in the table above. It is also the base of the history.

`ZapPlan` gets a `state` field: the state after the plan. The frontend
stores it and sends it back as `current` with the next request.

### 3. History

The history is a trail of states. Each entry has the prompt, the plan and
the state after it. It shows as a short list of rows:

```
⚡ Deforestation in Pará            Tree cover loss · Pará · 2001–2025
⚡ since 2015, primary forest       Tree cover loss · Pará · 2015–2025 · primary
⚡ fires instead                    Loss due to fires · Pará · 2015–2025     ← now
```

- A row is the prompt and the result as chips. It has no answer text and
  no speaker.
- A click on a row puts the map in that state.
- A new request applies to the state of the selected row. If the row is
  not the last row, the later rows are removed, as in browser history.
- A chip can open the other options of its decision. jev returns a
  probability for each option, so the plan can carry the top three. One
  click corrects a wrong dataset or area with no new request.

Storage: the trail is in the browser only (session storage). The backend
stores nothing. There is one trail for the map and one for each dashboard.
A trail keeps the last 20 rows. When a row is added to a full trail, the
oldest row is removed. A trail ends when the browser tab closes.

On a dashboard, a row is a record of what the request did. It shows the
prompt and the edit, for example "Added: Tree cover loss per year". A row
cannot put the dashboard back in an earlier state, so a click on it does
nothing more than show its decisions.

### 4. Undo

Undo is for the map only. Undo selects the row before the current row.
Redo selects the row after it. No server call is necessary, because a map
row holds the full state.

A dashboard has no undo button. A dashboard edit is in the database, and a
correct undo needs a stored snapshot or inverse operations. This plan does
not include that. The user takes back an edit with a new request or with
the page controls. Because of this:

- A removal always gets a confirmation (see "Tiers and confirmation").
- A removed widget does not delete its insight, so "add the tree cover loss
  chart again" can bring it back.
- The row of the last edit names the widget or the section, so a follow-up
  request such as "remove that" has a clear target. The planner gets the
  ids of the last edit in `current`, and the `target` question lists them
  first.

### 5. Zap on a dashboard

On a dashboard page, the first jev call gets an `action` question. The
area is the area of the dashboard, so the `place` field is not used.

| Action | What zap does | Tier |
|---|---|---|
| `add_chart` | Runs `/api/analyze` for the dataset and the period, then adds the insight as a widget | 1 |
| `add_map` | Adds a map widget for the dataset (`widget_configs.dataset_config`) | 1 |
| `add_template` | Applies an analysis template. jev selects one of the three templates | 1 |
| `add_imagery` | Adds a Sentinel-2 imagery widget. The date and `cloud` come from Clairic | 1 |
| `add_section` | Adds an empty section. The title is the `title` field | 1 |
| `move` | Moves a widget to a section or to the top level | 1 |
| `resize` | Sets a widget to half width or full width | 1 |
| `rename` | Changes the name of the dashboard or the title of a section to the `title` field | 1 |
| `change_period` | Builds one chart widget again for a new period and replaces it | 2 |
| `remove` | Removes a widget, or a section with or without its widgets | 2 |
| `none` | Changes nothing | |

The `target` question: for `move`, `resize`, `rename`, `change_period` and
`remove`, the second jev call selects the widget or the section. The options
are the titles of the widgets and the sections of the dashboard, and "none
of these". jev selected correctly from up to 250 options in the stac-zap
tests, and a dashboard has fewer.

The `view` question: when the dataset has more than one view in
`src/api/services/charts/views.py`, jev selects the view for `add_chart`.
This needs the view registry of the low AI mode plan (phase 1, not merged).

### 6. Tiers and confirmation

| Tier | Edits | Behaviour |
|---|---|---|
| 0 | Map changes | Applied immediately. Undo is local |
| 1 | Additions and layout changes on a dashboard | Applied immediately, if each decision is clear. No undo: a new request or the page controls take the edit back |
| 2 | Removals, replacements, an edit of more than one widget, and each tier 1 edit with a decision that is not clear | The plan shows as a preview. The user confirms or corrects it |
| 3 | Delete a dashboard, publish a dashboard, more than one area | Not in zap. A note sends the user to the page controls or to the assistant |

A decision is clear when the probability of the selected option is at
least 0.6 and at least 0.25 above the second option. For a Clairic field,
`p_null` must be below 0.2 or above 0.8. These numbers are a first value.
The eval sets them.

A confirmation is not only "yes" or "no". The preview shows the decision
that is not clear with its top options as chips, for example "Which
widget? [Tree cover loss per year] [Tree cover loss by driver]". One click
selects the option and applies the edit.

Publish is in tier 3 because it also makes the insights of the dashboard
public, and nothing can take that back for a person who already has the
link.

### 7. API

`POST /api/zap` stays the only zap endpoint, and it stays a planner. It
gets the full `current` and returns the steps, the decisions with their top
options, the `state`, a `tier` and `needs_confirmation`. It changes
nothing and stores nothing.

The frontend runs all steps, as it does for the map today. A dashboard
step uses the dashboard endpoints that exist:

| Step | Endpoint |
|---|---|
| `add_chart` | `POST /api/analyze`, then `POST /api/dashboards/{id}/widgets` with the insight |
| `add_map`, `add_imagery` | `POST /api/dashboards/{id}/widgets`. The plan step holds the widget config |
| `add_template` | `POST /api/dashboards/{id}/sections/from-template` |
| `add_section` | `POST /api/dashboards/{id}/sections` |
| `move`, `resize` | `PATCH /api/dashboards/{id}/widgets/{widget_id}` |
| `rename` | `PATCH /api/dashboards/{id}` or `PATCH .../sections/{section_id}` |
| `change_period` | `POST /api/analyze`, add the new widget at the position of the old widget, then remove the old widget |
| `remove` | `DELETE .../widgets/{widget_id}` or `DELETE .../sections/{section_id}` |

These endpoints are for the owner only, so zap needs no new access rule
and no new table. A plan with more than one step is not one transaction. If
a step fails, the steps before it stay, and the trail row shows which step
failed.

## Eval

Zap needs a labelled set before the Clairic change, so that the change can
be measured.

- **Map set.** The single-area gold prompts give the dataset, the area and
  the dates (the dates are in the `pull_data` arguments). Add requests that
  the option lists cannot hold: date ranges, months, long place names,
  canopy values. Add follow-up pairs.
- **Dashboard set.** Requests against two or three fixed dashboards, with
  the expected action, target and tier. Include requests that must get a
  confirmation and requests that must change nothing.
- As in stac-zap: write the field instructions on a dev part only, and run
  the test part one time.
- Report the wrong edits that were applied with no confirmation as a
  separate number. This number sets the thresholds.

## Baseline

Run on 2026-11-12 with jev `typesafe/jev-1.13`, the planner of `main` at
`1784eab6`, and the map set in `tests/evals/zap/` (51 dev cases, 53 test
cases). `scripts/zap_eval.py` runs the set. `tests/evals/zap/README.md`
gives the scoring rules. The raw results are in
`tests/evals/zap/results/2026-11-12-dev.json` and `2026-11-12-test.json`.

Correct values for each field:

| Field | Dev | Test | Total |
|---|---|---|---|
| Dataset | 51/51 | 53/53 | 104/104 (100%) |
| Area | 45/51 | 49/53 | 94/104 (90%) |
| Time | 32/50 | 36/51 | 68/101 (67%) |
| Context layer | 32/35 | 39/41 | 71/76 (93%) |
| Canopy cover | 29/29 | 31/33 | 60/62 (97%) |
| No change | 4/5 | 4/4 | 8/9 |
| All fields of a case | 25/51 | 32/53 | 57/104 (55%) |
| Median time of a plan | 562 ms | 558 ms | |

Cases with all tested fields correct, for each kind of case:

| Kind | Dev | Test | Total |
|---|---|---|---|
| Gold prompts | 9/21 | 16/23 | 25/44 |
| Gold prompts, other languages | 1/3 | 2/2 | 3/5 |
| Free date range | 0/2 | 0/3 | 0/5 |
| Month or day (alerts) | 0/3 | 0/3 | 0/6 |
| Period back from today | 1/3 | 2/3 | 3/6 |
| Place name of more than four words | 3/3 | 3/3 | 6/6 |
| Canopy cover value | 3/3 | 3/4 | 6/7 |
| Follow-up pairs | 4/8 | 4/8 | 8/16 |
| No change | 4/5 | 4/4 | 8/9 |

What the baseline shows:

- **Time is the weakest field.** jev changes each free range to the nearest
  option: "from 2015 to 2020" becomes "since 2015", "2010-2015" becomes
  the full record. Each month or day of the alerts becomes its year.
  "The last 3 months" and "the last 6 months" become the last 12 months.
  A range that ends before today, such as "between 2001 and 2024", also
  ends on the last date of the dataset.
- **The area fails in the `place` question, not in the area question.**
  In all 10 failures, the span that jev selected has extra words
  ("Corona Forestal protected area", "in Cogo Eq Guinea", "Las Palmas
  Canarias ESP"), a possessive ("Indonesia's"), a name that is not English
  ("España"), or no word breaks (Chinese). Then `search_aois` finds no
  area, or jev rejects all the areas that it finds.
- **Long place names did not fail.** `search_aois` found the area from a
  span of four words for all six cases. The limit of four words is real,
  but this set does not show it.
- **Follow-up requests lose the settings.** "since 2015" after "primary
  forest loss in Pará" drops the forest type. "fires instead" drops the
  forest type and the dates. "now show 2020" drops the canopy cover. "use
  a 75% canopy threshold" drops the forest type.
- **The dataset is always correct**, also in follow-up requests and in
  other languages.

Phase 2 must improve time and area on this set, with no loss on dataset,
context layer and canopy cover.

## Phase 2 result

Run on 2026-11-12 with jev `typesafe/jev-1.13`, Clairic
`cloudflare/clairic` (`cloudflare/clairic-20261029`) and the same map set
as the baseline. The field instructions and the calendar rules were tuned
on the dev part only. The test part ran one time, after the tuning. The raw
results are in `tests/evals/zap/results/2026-11-12-dev-phase2.json` and
`2026-11-12-test-phase2.json`.

A follow-up case now sends the `state` of the plan of its first prompt (see
`tests/evals/zap/README.md`). Thus, a wrong first plan also counts against
its follow-up. The baseline sent only the dataset and the area of the fixed
`current`.

Correct values for each field:

| Field | Dev | Test | Total | Baseline total |
|---|---|---|---|---|
| Dataset | 51/51 | 53/53 | 104/104 (100%) | 104/104 (100%) |
| Area | 48/51 | 51/53 | 99/104 (95%) | 94/104 (90%) |
| Time | 50/50 | 47/51 | 97/101 (96%) | 68/101 (67%) |
| Context layer | 34/35 | 40/41 | 74/76 (97%) | 71/76 (93%) |
| Canopy cover | 29/29 | 33/33 | 62/62 (100%) | 60/62 (97%) |
| No change | 5/5 | 4/4 | 9/9 | 8/9 |
| All fields of a case | 47/51 | 46/53 | 93/104 (89%) | 57/104 (55%) |
| Median time of a plan | 695 ms | 659 ms | | 562 ms, 558 ms |

Cases with all tested fields correct, for each kind of case:

| Kind | Dev | Test | Total | Baseline total |
|---|---|---|---|---|
| Gold prompts | 19/21 | 19/23 | 38/44 | 25/44 |
| Gold prompts, other languages | 1/3 | 2/2 | 3/5 | 3/5 |
| Free date range | 2/2 | 3/3 | 5/5 | 0/5 |
| Month or day (alerts) | 3/3 | 1/3 | 4/6 | 0/6 |
| Period back from today | 3/3 | 3/3 | 6/6 | 3/6 |
| Place name of more than four words | 3/3 | 3/3 | 6/6 | 6/6 |
| Canopy cover value | 3/3 | 4/4 | 7/7 | 6/7 |
| Follow-up pairs | 8/8 | 8/8 | 16/16 | 8/16 |
| No change | 5/5 | 4/4 | 9/9 | 8/9 |

The "done when" of phase 2 holds: time and area are better than the
baseline, and dataset, context layer and canopy cover are not worse.

What changed in the planner:

- Clairic call A (the request only) gives the place and the canopy cover.
  Clairic call B (the app context, today's date and the request) gives the
  time. Both calls and the first jev call start at the same time.
- Code makes the range for these time words: whole years ("in 2025",
  "2015-2020", "since 2015", "until 2010"), months in English ("March
  2026", "from January to April 2025", "since May"), seasons, quarters,
  half years, periods back from today, "recent" (the last 12 months, as the
  jev option) and "all years". On the dev part, Clairic gave a wrong last
  day for most years and some months, for example 2026-12-12 for "in 2025"
  and 2026-03-02 for "March 2026". "Today" or "now" alone names no time.
  In the two runs, code made 56 of the 104 ranges.
- When `search_aois` finds nothing for the place words, the planner tries
  again with a cleaned name: no type word at the end ("Corona Forestal
  protected area"), no possessive, no text in brackets, and a comma in place
  of "in" ("Pocho in Cordoba").
- The canopy cover snaps to the nearest value of the dataset. A value more
  than 5 points from a permitted value adds a note.
- The planner starts from the full `current` and changes only what the
  request names. jev gets a `keep` option for the forest type when the map
  shows one. When the current dates are all the dates of the current
  dataset, they do not count as a selected period.
- Each decision has a `source`: `jev`, `clairic` or `code`. `ZapPlan.state`
  is the state after the steps.
- A Clairic call that gets a 429 or a 5xx error tries again one time after
  0.3 s. The dev runs got "Capacity temporarily exceeded" (429) when many
  calls ran at the same time.

The fallback: the first jev call also asks the `place` and `period`
questions of phase 1, so a Clairic failure adds no time. When call A fails,
the planner uses the jev place and asks the jev `canopy` question. When
call B fails, or its answers make no range, the planner uses the jev period.
The unit tests cover each case. A dev run with a wrong extractions URL
(all Clairic calls fail) gave dataset 51/51, area 47/51, time 31/50, context
layer 32/35, canopy cover 29/29, no change 4/5 and all fields 26/51, with
each value from jev. This is near the dev baseline (45, 32, 32, 29, 4 and
25).

The cost: the median time of a plan increased by about 120 ms. The first
jev call still asks the `place` and `period` questions, so the jev cost
did not decrease, and the two Clairic calls add about $0.00004 each.

The cases that still fail:

| Case | Field | Cause |
|---|---|---|
| d-14, d-16 | Area | The name is not English ("España", "中国"). Clairic gives the words of the request and does not translate them. `search_aois` finds English names only |
| d-10 | Area | jev selects the municipality of Huelva, not the province (probability 0.5) |
| t-05 | Area | The place words "Blackfeet Indian reservation in Montana USA" find no area, also in the cleaned form. The baseline found it from a shorter span. A new failure |
| t-06 | Area | "Champoton community land in Mexico" finds no area. The baseline also failed |
| d-23, t-12 | Context layer | jev selects no forest type for "deforestation". The baseline also failed |
| t-15 | Time | The request compares two months. Clairic gives the first month only. The expected range has both months |
| t-20 | Time | The request compares two periods. Clairic gives the first period, 2000-2010. The expected range is the whole record. A new failure |
| t-30 | Time | "last month": Clairic gives 2026-10-01 to 2026-10-12, not the full month. The rule for a period back from today leaves "last month" to Clairic |
| t-31 | Time | "between December 2024 and February 2025": the month rule takes only one year, and Clairic ends on 2025-02-02 |

Possible next steps, from these failures: a month rule for "last month"
and for a range of months over two years, a cleaned form that removes
words such as "Indian reservation" and "community land", and English
names before `search_aois`. Add dev cases for each before a change, because
t-30 and t-31 are in the test part.

## Phases

Each phase is one or more PRs and can ship alone behind `ff=zap`.

| Phase | Content | Done when |
|---|---|---|
| 1 (done, 2026-11-12) | Map eval set and script. Baseline of zap today | The baseline numbers are in this document (see "Baseline") |
| 2 (done, 2026-11-12) | `extract.py` with the jev fallback. Full `ZapCurrent`. `state` in the plan | The map set is better than the baseline on time and area, and not worse on dataset, context layer and canopy cover |
| 3 | History trail in the browser, with its row limit, and undo on the map (frontend). Top options in the decisions | A follow-up request keeps the earlier settings; undo and row selection restore the map |
| 4 | Zap on dashboards, tier 1 additions: `action` question, the dashboard steps in the frontend, the dashboard trail | A request adds a chart, a map, a template or imagery to a dashboard, and the trail shows the edit |
| 5 | Tier 1 layout edits and tier 2 edits: `target` question, preview and confirmation, thresholds from the dashboard set | No wrong removal is applied with no confirmation in the dashboard set; "remove that" after an addition removes the added widget |
| 6 | `view` question, after the view registry merges | `add_chart` can select each view of a dataset |

## Risks

- **Alpha APIs.** The decisions API and the extractions API are alpha, and
  Clairic is a preview. The fallback covers Clairic. Nothing covers jev.
- **Declines.** jev declines poorly (PR #841). On a dashboard, a wrong
  `action` is worse than on the map, because it writes data. Tier 2 and the
  thresholds are the protection, and the dashboard set must have decline
  cases.
- **No undo on dashboards.** A wrong tier 1 edit stays until the user
  corrects it. Additions and layout changes are easy to correct. A wrong
  `change_period` loses the old period of the widget, which is why it is
  in tier 2.
- **Steps that fail in the middle.** The frontend runs the steps one by
  one, so a failure can leave a part of the plan applied.
- **English only.** The calendar rules in code read English words. Other
  languages use the `start` and `end` dates of Clairic with no rule.
- **Analysis time.** `add_chart` waits for an `/api/analyze` job. The
  frontend adds the widget when the job ends, as `ZapRunner` does for the
  chart step today. If the user leaves the page before that, the insight
  exists but the widget does not.

## Decisions

Agreed on 2026-11-12:

- **History storage.** The browser only, with a row limit. The backend
  stores no history.
- **Undo on dashboards.** None in this plan. The user makes a new request
  to take back an edit. A real undo can come later.

Open, for agreement before phase 2:

1. **Where dashboard steps run.** Proposed: in the frontend, through the
   dashboard endpoints that exist. With no undo, a server apply endpoint
   has no clear benefit. It can come with a real undo.
2. **`change_period`.** Proposed: replace the widget after a confirmation.
   The alternative keeps the old widget and adds the new one next to it,
   which loses nothing but leaves the user to remove the old one.
3. **Text.** Proposed: zap writes no text. A name or a note is the words of
   the user from the `title` field. Text widgets with new text stay with
   the assistant.
4. **Access.** Proposed: admins only and `ff=zap` until phase 5 passes its
   eval.
5. **Phase order.** Proposed: extraction first, because the dashboard
   actions need correct dates. If dashboards are more urgent, phase 4 can
   go before phase 3.
